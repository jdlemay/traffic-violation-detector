"""Camera / video capture.

`open_source` accepts an int camera index, a device path, a GStreamer pipeline
string, or a video file (dev). On the Jetson prefer a GStreamer pipeline using
the HW elements (`nvarguscamerasrc`/`nvv4l2camerasrc`) for zero-copy capture.

Frames are yielded with a monotonic-ish timestamp. If OpenCV is unavailable the
capture raises a clear error (the pipeline can also run in `--sim` mode which
generates blank frames for logic testing).
"""
from __future__ import annotations

import time
from typing import Iterator, Optional, Tuple

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


def jetson_csi_pipeline(width: int, height: int, fps: int, sensor_id: int = 0) -> str:
    """A sensible GStreamer pipeline for a Jetson CSI camera."""
    return (
        f"nvarguscamerasrc sensor-id={sensor_id} ! "
        f"video/x-raw(memory:NVMM),width={width},height={height},"
        f"framerate={fps}/1 ! nvvidconv ! video/x-raw,format=BGRx ! "
        f"videoconvert ! video/x-raw,format=BGR ! appsink drop=true max-buffers=2"
    )


class Camera:
    def __init__(self, source, width=1920, height=1080, fps=30):
        self.source = source
        self.width, self.height, self.fps = width, height, fps
        self._cap = None

    def open(self) -> "Camera":
        if cv2 is None:
            raise RuntimeError("OpenCV not installed; use --sim for logic testing")
        src = self.source
        if isinstance(src, str) and src.isdigit():
            src = int(src)
        self._cap = cv2.VideoCapture(src)
        if isinstance(src, int):
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self._cap.set(cv2.CAP_PROP_FPS, self.fps)
        if not self._cap.isOpened():
            raise RuntimeError(f"failed to open capture source: {self.source}")
        return self

    def frames(self) -> Iterator[Tuple[float, np.ndarray]]:
        assert self._cap is not None, "call open() first"
        while True:
            ok, frame = self._cap.read()
            if not ok:
                break
            yield time.time(), frame

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()


class SimCamera:
    """Generates blank frames at the configured size/fps for logic testing."""
    def __init__(self, width=1280, height=720, fps=30, n=None):
        self.width, self.height, self.fps, self.n = width, height, fps, n

    def open(self):
        return self

    def frames(self) -> Iterator[Tuple[float, np.ndarray]]:
        i = 0
        period = 1.0 / max(1, self.fps)
        while self.n is None or i < self.n:
            frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            yield time.time(), frame
            i += 1
            time.sleep(period)

    def release(self):
        pass


def open_source(source, width, height, fps, sim=False):
    if sim or source in (None, "sim"):
        return SimCamera(width, height, fps)
    return Camera(source, width, height, fps).open()
