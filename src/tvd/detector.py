"""YOLO detection + tracking wrapper (Ultralytics).

On the Jetson, point `model` at a TensorRT `.engine` exported with
`yolo export ... format=engine half=True` for the big speedup. Tracking uses
Ultralytics' built-in ByteTrack/BoT-SORT (config in `tracker`).

If Ultralytics/torch aren't installed (e.g. minimal dev box), the detector
degrades to returning no tracks so the rest of the pipeline still runs.
"""
from __future__ import annotations

from typing import Any, Optional

from .violations.base import Track

# COCO id -> label for the classes we keep.
COCO_LABELS = {
    0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus",
    7: "truck", 9: "traffic light", 11: "stop sign",
}


class Detector:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.keep = set(cfg.get("keep_classes", list(COCO_LABELS)))
        self.conf = float(cfg.get("conf_threshold", 0.35))
        self.iou = float(cfg.get("iou_threshold", 0.5))
        self.imgsz = int(cfg.get("imgsz", 640))
        self.tracker = cfg.get("tracker", "bytetrack.yaml")
        self.device = cfg.get("device", "cuda:0")
        self._model = None
        self._load(cfg.get("model", "yolo11s.pt"))

    def _load(self, weights: str) -> None:
        try:
            from ultralytics import YOLO  # heavy import, guarded
            self._model = YOLO(weights)
        except Exception as exc:  # pragma: no cover - env dependent
            print(f"[detector] Ultralytics/model unavailable ({exc}); "
                  f"running with empty detections.")
            self._model = None

    def available(self) -> bool:
        return self._model is not None

    def track(self, frame) -> list[Track]:
        """Detect + track on one BGR frame; return kept-class tracks."""
        if self._model is None:
            return []
        results = self._model.track(
            frame, persist=True, conf=self.conf, iou=self.iou,
            imgsz=self.imgsz, tracker=self.tracker, device=self.device,
            classes=list(self.keep), verbose=False,
        )
        if not results:
            return []
        r = results[0]
        out: list[Track] = []
        boxes = getattr(r, "boxes", None)
        if boxes is None:
            return out
        for b in boxes:
            cls = int(b.cls[0])
            if cls not in self.keep:
                continue
            tid = int(b.id[0]) if b.id is not None else -1
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
            out.append(Track(
                track_id=tid, cls=cls,
                label=COCO_LABELS.get(cls, str(cls)),
                conf=float(b.conf[0]), bbox=(x1, y1, x2, y2),
            ))
        return out
