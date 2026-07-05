"""Core types for the rule engine.

`Track` and `FrameContext` are the inputs a detector sees each tick; `Event` is
what it emits. Detectors are pure functions of (context) -> Optional[Event],
which makes them trivial to unit-test without cameras or a GPU.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..sensors.state import SensorSnapshot


@dataclass(frozen=True)
class Track:
    """One tracked object for one frame."""
    track_id: int
    cls: int                      # class id (COCO)
    label: str                    # human label, e.g. "car"
    conf: float
    bbox: tuple[float, float, float, float]   # x1,y1,x2,y2 (pixels)

    @property
    def cx(self) -> float:
        return 0.5 * (self.bbox[0] + self.bbox[2])

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def area(self) -> float:
        return (self.bbox[2] - self.bbox[0]) * (self.bbox[3] - self.bbox[1])


@dataclass
class FrameContext:
    """Everything a detector needs for one frame."""
    ts: float                     # frame timestamp (epoch seconds)
    frame_w: int
    frame_h: int
    tracks: list[Track]
    sensors: SensorSnapshot
    homography: Any = None        # np.ndarray or None
    dt: float = 0.0               # seconds since previous frame


@dataclass(frozen=True)
class Event:
    """A detected violation / safety event."""
    type: str
    tier: int
    confidence: float
    ts: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)
    degraded: bool = False        # a required sensor was missing


class ViolationDetector:
    """Base class. Subclasses implement `update(ctx) -> Optional[Event]`.

    Detectors may keep internal temporal state (previous distances, timers).
    The engine owns cross-detector concerns (cooldown, confidence gating).
    """

    #: unique event type string this detector emits
    type: str = "generic"
    #: difficulty tier (see docs/01)
    tier: int = 1

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg or {}
        self.enabled: bool = bool(self.cfg.get("enabled", True))

    def update(self, ctx: FrameContext) -> Optional[Event]:  # pragma: no cover
        raise NotImplementedError
