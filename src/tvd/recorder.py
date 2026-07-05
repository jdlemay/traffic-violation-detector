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
        this `post_s` seconds after the event (the pipeline schedules it). Returns
        the clip path, or None if no segments were available.
        """
        t0 = event_ts - self.pre_s
        t1 = event_ts + self.post_s
        segs = self.ring.segments_covering(t0, t1)
        if not segs:
            return None

        out_path = os.path.join(self.out_dir, f"{name}.{self.container}")
        list_path = os.path.join(self.out_dir, f"{name}.ffconcat.txt")
        with open(list_path, "w") as f:
            for s in segs:
                f.write(f"file '{os.path.abspath(s.path)}'\n")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
                 "-c", "copy", out_path],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        finally:
            try:
                os.remove(list_path)
            except OSError:
                pass
        return out_path
