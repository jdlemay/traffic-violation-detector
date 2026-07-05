"""Optional license-plate detection + OCR (ALPR).

Privacy note (docs/06): by default this runs *only when attached to an event*
(`privacy.alpr_on_event_only`), never as a continuous plate log.

Two-stage: a plate detector localizes the plate on a vehicle crop, then an OCR
model reads it. Both are pluggable; this module wraps them and degrades to
returning None when the libraries/models are absent so the pipeline still runs.
Recommended engines: fast-plate-ocr or PaddleOCR (see requirements.txt).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PlateResult:
    text: str
    confidence: float


class Alpr:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.enabled = bool(self.cfg.get("enabled", False))
        self._engine = None
        if self.enabled:
            self._load()

    def _load(self) -> None:
        try:
            # Example wiring (uncomment once installed):
            # from fast_plate_ocr import ONNXPlateRecognizer
            # self._engine = ONNXPlateRecognizer("global-plates-mobile-vit-v2-model")
            self._engine = None
        except Exception as exc:  # pragma: no cover
            print(f"[alpr] engine unavailable ({exc}); OCR disabled")
            self._engine = None

    def read(self, plate_crop) -> Optional[PlateResult]:
        """Return the recognized plate text + confidence, or None."""
        if not self.enabled or self._engine is None:
            return None
        # result = self._engine.run(plate_crop)
        # return PlateResult(text=result.text, confidence=result.confidence)
        return None
