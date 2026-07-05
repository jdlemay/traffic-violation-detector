"""Tier-1: lane departure of the ego vehicle.

Design (see docs/05): detect the left/right lane lines in the forward camera,
compute the vehicle's lateral offset from lane center, and flag a crossing that
happens with lateral velocity toward the line and no active turn signal.

This module ships the *rule* logic operating on a `LaneState` (offset + which
line is being crossed). The lane-line *extraction* from pixels is intentionally
pluggable: a classic-CV extractor is provided as a starting point and can be
swapped for a learned lane model (CLRNet/LaneNet) later without touching the
rule. When no lane extractor/frame is wired in, the detector is inert (returns
None) rather than guessing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .base import Event, FrameContext, ViolationDetector


@dataclass
class LaneState:
    # Normalized lateral offset from lane center in [-1, 1]; +1 = right line.
    offset: float
    # True when the vehicle footprint has crossed a lane line this frame.
    crossing: bool
    side: Optional[str] = None   # 'left' | 'right'


class LaneDepartureDetector(ViolationDetector):
    type = "lane_departure"
    tier = 1

    def __init__(self, cfg, lane_extractor=None):
        super().__init__(cfg)
        self.require_no_signal = bool(self.cfg.get("require_no_signal", True))
        # lane_extractor: callable(frame) -> LaneState | None. Injected by the
        # pipeline; None on dev machines without a lane model wired in.
        self._extract = lane_extractor
        self._prev_offset: Optional[float] = None

    def update(self, ctx: FrameContext) -> Optional[Event]:
        # The pipeline stashes the current frame on ctx via `meta` when a lane
        # extractor is present; without one this detector stays inert.
        lane: Optional[LaneState] = getattr(ctx, "lane_state", None)
        if lane is None or self._extract is None:
            return None

        moving_toward = False
        if self._prev_offset is not None:
            delta = lane.offset - self._prev_offset
            moving_toward = (lane.side == "right" and delta > 0) or (
                lane.side == "left" and delta < 0)
        self._prev_offset = lane.offset

        if not (lane.crossing and moving_toward):
            return None

        # Suppress intentional lane changes if a matching signal is active.
        signal = ctx.sensors.obd.turn_signal
        if self.require_no_signal and signal is not None and signal == lane.side:
            return None

        degraded = signal is None and self.require_no_signal
        conf = 0.55 if degraded else 0.8
        return Event(self.type, self.tier, conf, ts=ctx.ts,
                     meta={"side": lane.side, "offset": round(lane.offset, 2),
                           "signal_known": signal is not None},
                     degraded=degraded)
