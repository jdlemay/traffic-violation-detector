"""Tier-2: stop-sign compliance for the ego vehicle.

Approach (see docs/05): a stop sign's bounding box grows as we approach it. We
run a small state machine — once a stop sign is large enough that we're at/near
the line, we track the *minimum* ego speed over the approach. When the sign
leaves the frame (we've passed it), we evaluate: if the minimum speed never fell
to ~0, that's a rolling stop.

Requires ego speed (OBD/GPS). Without it the detector is inert (it will not guess
compliance from video alone).
"""
from __future__ import annotations

from typing import Optional

from .base import Event, FrameContext, Track, ViolationDetector

STOP_SIGN_LABEL = "stop sign"


class StopSignComplianceDetector(ViolationDetector):
    type = "stop_sign_violation"
    tier = 2

    def __init__(self, cfg):
        super().__init__(cfg)
        # Speed at/below which we consider the vehicle "stopped".
        self.stop_speed = float(self.cfg.get("stop_speed_mps", 0.5))
        # Sign bbox area (fraction of frame) above which we're "at the line".
        self.enter_area_frac = float(self.cfg.get("enter_area_frac", 0.004))
        # Consider the sign "passed" once unseen for this long.
        self.lost_seconds = float(self.cfg.get("lost_seconds", 0.8))
        # state
        self._approaching = False
        self._min_speed: Optional[float] = None
        self._last_seen: float = 0.0
        self._had_speed = False

    def _largest_stop_sign(self, ctx: FrameContext) -> Optional[Track]:
        signs = [t for t in ctx.tracks if t.label == STOP_SIGN_LABEL]
        return max(signs, key=lambda t: t.area) if signs else None

    def update(self, ctx: FrameContext) -> Optional[Event]:
        frame_area = max(1.0, ctx.frame_w * ctx.frame_h)
        sign = self._largest_stop_sign(ctx)
        speed = ctx.sensors.best_speed_mps()

        near = sign is not None and (sign.area / frame_area) >= self.enter_area_frac
        if near:
            if not self._approaching:
                self._approaching = True
                self._min_speed = None
                self._had_speed = False
            self._last_seen = ctx.ts
            if speed is not None:
                self._had_speed = True
                self._min_speed = speed if self._min_speed is None else min(self._min_speed, speed)
            return None

        # Not near a sign this frame. If we were approaching and the sign has
        # been gone long enough, we've passed it -> evaluate compliance.
        if self._approaching and (ctx.ts - self._last_seen) >= self.lost_seconds:
            event = self._evaluate(ctx)
            self._reset()
            return event
        return None

    def _evaluate(self, ctx: FrameContext) -> Optional[Event]:
        if not self._had_speed or self._min_speed is None:
            return None  # inert without speed evidence
        if self._min_speed <= self.stop_speed:
            return None  # complied (came to a stop)
        # Rolling stop. Confidence grows with how fast we were at the line.
        conf = min(1.0, 0.5 + 0.1 * (self._min_speed - self.stop_speed))
        return Event(
            type=self.type, tier=self.tier, confidence=conf, ts=ctx.ts,
            meta={"min_speed_mps": round(self._min_speed, 2),
                  "stop_threshold_mps": self.stop_speed,
                  "kind": "rolling_stop"},
        )

    def _reset(self):
        self._approaching = False
        self._min_speed = None
        self._had_speed = False
