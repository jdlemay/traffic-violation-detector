"""Pre/post-event video recording via a continuous segment ring buffer.

Strategy (see docs/02 §Design principles, docs/07 §9): continuously write short
fixed-length segments to disk (ideally via the HW encoder / GStreamer splitmux
on the Jetson). On an event, assemble a clip covering [t-pre, t+post] by
concatenating the relevant already-encoded segments — no giant RAM buffer, no
CPU re-encode. Old segments are pruned to bound disk use.

Two layers:
  * SegmentRingBuffer  — bookkeeping of on-disk segments (pure, testable).
  * ClipRecorder       — assembles event clips via ffmpeg concat.

This module keeps the bookkeeping pure/testable; the actual segment *encoding*
is done by the capture/GStreamer layer on device (a portable OpenCV/ffmpeg
fallback is provided for dev).
"""
from __future__ import annotations

import bisect
import os
import subprocess
from dataclasses import dataclass
from typing import List, Optional


@dataclass(order=True)
class Segment:
    start_ts: float
    end_ts: float
    path: str


class SegmentRingBuffer:
    """Tracks encoded segments and prunes beyond a retention horizon."""

    def __init__(self, archive_dir: str, keep_seconds: float = 900.0):
        self.archive_dir = archive_dir
        self.keep_seconds = keep_seconds
        self._segments: List[Segment] = []
        os.makedirs(archive_dir, exist_ok=True)

    def add(self, seg: Segment) -> None:
        self._segments.append(seg)
        self._segments.sort(key=lambda s: s.start_ts)
        self._prune(seg.end_ts)

    def _prune(self, now_ts: float) -> None:
        horizon = now_ts - self.keep_seconds
        keep: List[Segment] = []
        for s in self._segments:
            if s.end_ts < horizon:
                try:
                    os.remove(s.path)
                except OSError:
                    pass
            else:
                keep.append(s)
        self._segments = keep

    def segments_covering(self, t0: float, t1: float) -> List[Segment]:
        """All segments overlapping [t0, t1], in time order."""
        return [s for s in self._segments if s.end_ts >= t0 and s.start_ts <= t1]


class SegmentWriter:
    """Encodes incoming frames into fixed-length segment files and registers
    them with the ring buffer.

    This is the portable dev implementation (OpenCV VideoWriter, mp4v). On the
    Jetson, replace with a GStreamer `splitmuxsink` pipeline using the NVENC HW
    encoder — same Segment bookkeeping, near-zero CPU cost. Frames are written
    on the caller's thread; at 1080p30 with mp4v this is fine for dev but the
    HW path is required for production (see docs/02 §6).

    Degrades to a no-op when OpenCV is unavailable so the pipeline still runs.
    """

    def __init__(self, ring: SegmentRingBuffer, fps: int = 30,
                 segment_seconds: float = 2.0):
        self.ring = ring
        self.fps = max(1, int(fps))
        self.segment_seconds = segment_seconds
        self._writer = None
        self._seg_start: float = 0.0
        self._seg_path: str = ""
        self._seq = 0
        try:
            import cv2
            self._cv2 = cv2
        except Exception:  # pragma: no cover - env dependent
            self._cv2 = None

    @property
    def active(self) -> bool:
        return self._cv2 is not None

    def write(self, ts: float, frame) -> None:
        if self._cv2 is None:
            return
        if self._writer is not None and ts - self._seg_start >= self.segment_seconds:
            self._finalize(ts)
        if self._writer is None:
            self._open(ts, frame)
        self._writer.write(frame)

    def _open(self, ts: float, frame) -> None:
        h, w = frame.shape[:2]
        self._seq += 1
        self._seg_path = os.path.join(self.ring.archive_dir,
                                      f"seg_{self._seq:08d}.mp4")
        fourcc = self._cv2.VideoWriter_fourcc(*"mp4v")
        self._writer = self._cv2.VideoWriter(self._seg_path, fourcc,
                                             self.fps, (w, h))
        self._seg_start = ts

    def _finalize(self, end_ts: float) -> None:
        if self._writer is None:
            return
        self._writer.release()
        self._writer = None
        self.ring.add(Segment(start_ts=self._seg_start, end_ts=end_ts,
                              path=self._seg_path))

    def close(self, end_ts: Optional[float] = None) -> None:
        import time as _time
        self._finalize(end_ts if end_ts is not None else _time.time())


class ClipRecorder:
    def __init__(self, ring: SegmentRingBuffer, out_dir: str,
                 pre_s: float = 10.0, post_s: float = 10.0, container: str = "mp4"):
        self.ring = ring
        self.out_dir = out_dir
        self.pre_s = pre_s
        self.post_s = post_s
        self.container = container
        os.makedirs(out_dir, exist_ok=True)

    def assemble(self, event_ts: float, name: str) -> Optional[str]:
        """Concatenate segments covering [event_ts-pre, event_ts+post].

        NOTE: post-roll segments must already exist, so the caller should invoke
        this `post_s` seconds after the event (the pipeline schedules it).

        Prefers a lossless ffmpeg stream-copy concat; if ffmpeg is unavailable
        it falls back to re-encoding with OpenCV so evidence is still saved.
        Failures are logged, never silent — this is the evidence path.
        """
        t0 = event_ts - self.pre_s
        t1 = event_ts + self.post_s
        segs = self.ring.segments_covering(t0, t1)
        if not segs:
            print(f"[recorder] no segments cover event window "
                  f"[{t0:.1f}, {t1:.1f}] — clip '{name}' not saved")
            return None

        out_path = os.path.join(self.out_dir, f"{name}.{self.container}")
        if self._concat_ffmpeg(segs, out_path):
            return out_path
        if self._concat_opencv(segs, out_path):
            print(f"[recorder] ffmpeg unavailable/failed; clip '{name}' "
                  f"assembled via OpenCV re-encode fallback")
            return out_path
        print(f"[recorder] FAILED to assemble clip '{name}' "
              f"({len(segs)} segments) — install ffmpeg or opencv")
        return None

    def _concat_ffmpeg(self, segs: List[Segment], out_path: str) -> bool:
        list_path = out_path + ".ffconcat.txt"
        with open(list_path, "w") as f:
            for s in segs:
                f.write(f"file '{os.path.abspath(s.path)}'\n")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
                 "-c", "copy", out_path],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
        finally:
            try:
                os.remove(list_path)
            except OSError:
                pass

    def _concat_opencv(self, segs: List[Segment], out_path: str) -> bool:
        try:
            import cv2
        except Exception:
            return False
        writer = None
        try:
            for s in segs:
                cap = cv2.VideoCapture(s.path)
                while True:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    if writer is None:
                        h, w = frame.shape[:2]
                        fps = cap.get(cv2.CAP_PROP_FPS) or 30
                        writer = cv2.VideoWriter(
                            out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
                    writer.write(frame)
                cap.release()
            return writer is not None
        finally:
            if writer is not None:
                writer.release()
