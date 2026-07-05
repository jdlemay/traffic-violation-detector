"""Thread-safe latest-value sensor state.

The rule engine wants "what is true *now*" (current speed, latest IMU sample),
not a backlog. So sensor threads write into this store and the rules thread
reads the most recent values. All access is mutex-guarded.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from typing import Optional


@dataclass(frozen=True)
class GpsFix:
    ts: float
    lat: Optional[float] = None
    lon: Optional[float] = None
    speed_mps: Optional[float] = None   # GPS-derived speed (fallback)
    heading_deg: Optional[float] = None
    valid: bool = False


@dataclass(frozen=True)
class ImuSample:
    ts: float
    ax: float = 0.0   # m/s^2, vehicle longitudinal (+forward)
    ay: float = 0.0   # m/s^2, lateral (+right)
    az: float = 9.81  # m/s^2, vertical (includes gravity by default)
    gz: float = 0.0   # rad/s, yaw rate


@dataclass(frozen=True)
class ObdSample:
    ts: float
    speed_mps: Optional[float] = None
    rpm: Optional[float] = None
    throttle: Optional[float] = None
    turn_signal: Optional[str] = None   # 'left'|'right'|None (if exposed)


@dataclass
class SensorState:
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    gps: GpsFix = field(default_factory=lambda: GpsFix(ts=0.0))
    imu: ImuSample = field(default_factory=lambda: ImuSample(ts=0.0))
    obd: ObdSample = field(default_factory=lambda: ObdSample(ts=0.0))

    def update_gps(self, fix: GpsFix) -> None:
        with self._lock:
            self.gps = fix

    def update_imu(self, s: ImuSample) -> None:
        with self._lock:
            self.imu = s

    def update_obd(self, s: ObdSample) -> None:
        with self._lock:
            self.obd = s

    def snapshot(self) -> "SensorSnapshot":
        with self._lock:
            return SensorSnapshot(gps=self.gps, imu=self.imu, obd=self.obd)


@dataclass(frozen=True)
class SensorSnapshot:
    """An immutable read of all sensors at one instant, for a rule tick."""
    gps: GpsFix
    imu: ImuSample
    obd: ObdSample

    def best_speed_mps(self) -> Optional[float]:
        """Prefer OBD wheel speed; fall back to GPS speed. See docs/07."""
        if self.obd.speed_mps is not None:
            return self.obd.speed_mps
        if self.gps.valid and self.gps.speed_mps is not None:
            return self.gps.speed_mps
        return None
