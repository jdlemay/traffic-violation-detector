"""Tier-1: collision / hard impact detection from the IMU.

A collision shows up as a large net acceleration spike (well above the ~0.4 g
of hard braking), optionally corroborated by a sudden speed drop from OBD. We
subtract gravity by using the acceleration magnitude minus 1 g, which is robust
to mounting orientation.
"""
from __future__ import annotations

import math
from typing import Optional

from .base import Event, FrameContext, ViolationDetector

G = 9.80665


class CollisionDetector(ViolationDetector):
    type = "collision"
    tier = 1

    def __init__(self, cfg):
        super().__init__(cfg)
        self.threshold_g = float(self.cfg.get("threshold_g", 2.5))
        self.corroborate_drop = float(self.cfg.get("corroborate_speed_drop_mps", 3.0))
        self._last_speed: Optional[float] = None

    def update(self, ctx: FrameContext) -> Optional[Event]:
        imu = ctx.sensors.imu
        # Net acceleration over gravity (mounting-orientation independent).
        mag = math.sqrt(imu.ax**2 + imu.ay**2 + imu.az**2)
        net_g = abs(mag - G) / G

        speed = ctx.sensors.best_speed_mps()
        speed_drop = 0.0
        if speed is not None and self._last_speed is not None:
            speed_drop = max(0.0, self._last_speed - speed)
        self._last_speed = speed

        if net_g < self.threshold_g:
            return None

        # Confidence scales with severity and speed-drop corroboration.
        conf = min(1.0, 0.5 + 0.15 * (net_g - self.threshold_g))
        corroborated = speed_drop >= self.corroborate_drop
        if corroborated:
            conf = min(1.0, conf + 0.3)

        return Event(
            type=self.type,
            tier=self.tier,
            confidence=conf,
            ts=ctx.ts,
            meta={
                "net_g": round(net_g, 2),
                "speed_drop_mps": round(speed_drop, 2),
                "corroborated_by_speed": corroborated,
            },
        )
