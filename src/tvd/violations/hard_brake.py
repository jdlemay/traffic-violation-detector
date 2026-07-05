"""Tier-1: harsh driving events (hard braking, harsh acceleration, hard
cornering) from IMU longitudinal/lateral acceleration.

These double as safety-coaching signals and as pre-triggers that keep the video
ring buffer around near-misses.
"""
from __future__ import annotations

from typing import Optional

from .base import Event, FrameContext, ViolationDetector

G = 9.80665


class HarshDrivingDetector(ViolationDetector):
    type = "harsh_driving"
    tier = 1

    def __init__(self, cfg):
        super().__init__(cfg)
        self.decel_g = float(self.cfg.get("decel_g", 0.4))
        self.accel_g = float(self.cfg.get("accel_g", 0.4))
        self.lateral_g = float(self.cfg.get("lateral_g", 0.45))

    def update(self, ctx: FrameContext) -> Optional[Event]:
        imu = ctx.sensors.imu
        ax_g = imu.ax / G      # + forward accel, - deceleration
        ay_g = imu.ay / G      # lateral

        kind = None
        value = 0.0
        if ax_g <= -self.decel_g:
            kind, value = "hard_brake", -ax_g
        elif ax_g >= self.accel_g:
            kind, value = "harsh_accel", ax_g
        elif abs(ay_g) >= self.lateral_g:
            kind, value = "hard_corner", abs(ay_g)

        if kind is None:
            return None

        # Confidence grows past the threshold, capped.
        thr = {"hard_brake": self.decel_g, "harsh_accel": self.accel_g,
               "hard_corner": self.lateral_g}[kind]
        conf = min(1.0, 0.6 + 0.5 * (value - thr))
        return Event(
            type=self.type,
            tier=self.tier,
            confidence=conf,
            ts=ctx.ts,
            meta={"kind": kind, "g": round(value, 2)},
        )
