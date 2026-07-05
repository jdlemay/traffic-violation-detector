"""Tier-2: red-light entry for the ego vehicle.

Approach (see docs/05): track the governing traffic light's state
(red/yellow/green) and detect the ego vehicle crossing the stop line while the
light is red and we're moving forward.

Light *state classification* needs the pixels of the light crop (a small
red/yellow/green classifier on the detected `traffic light` box) and the
stop-line crossing needs geometry — both are perception concerns produced
upstream. So, like lane departure, this module implements the **rule** over an
injected `LightState` (set on the context by the pipeline's light-state
estimator). Without that estimator wired in, the detector is inert.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .base import Event, FrameContext, ViolationDetector


@dataclass
class LightState:
    color: str                 # 'red' | 'yellow' | 'green' | 'unknown'
    governing: bool            # is this the signal controlling our lane?
    crossing_stop_line: bool   # did the ego cross the stop line this frame?


class RedLightEntryDetector(ViolationDetector):
    type = "red_light_violation"
    tier = 2

    def __init__(self, cfg):
        super().__init__(cfg)
        # Treat entering on yellow as a violation too? Default no.
        self.flag_yellow = bool(self.cfg.get("flag_yellow", False))
        self.min_speed_mps = float(self.cfg.get("min_speed_mps", 1.0))

    def update(self, ctx: FrameContext) -> Optional[Event]:
        light: Optional[LightState] = getattr(ctx, "light_state", None)
        if light is None or not light.governing or not light.crossing_stop_line:
            return None

        offending = light.color == "red" or (self.flag_yellow and light.color == "yellow")
        if not offending:
            return None

        # Must be moving forward through the intersection.
        speed = ctx.sensors.best_speed_mps()
        if speed is not None and speed < self.min_speed_mps:
            return None

        degraded = speed is None
        conf = 0.6 if degraded else 0.85
        return Event(
            type=self.type, tier=self.tier, confidence=conf, ts=ctx.ts,
            meta={"light_color": light.color,
                  "speed_mps": None if speed is None else round(speed, 2)},
            degraded=degraded,
        )
