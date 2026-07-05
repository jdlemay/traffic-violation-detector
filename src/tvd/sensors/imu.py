"""IMU reader (I2C).

Backends:
  * i2c — read a BNO085/ICM-20948-class part over smbus2. The register map is
    part-specific; the method below is a clearly-marked template you adapt to
    your chosen IMU's datasheet.
  * sim — quiet IMU at rest (gravity on Z) with occasional synthetic events, so
    collision/hard-brake logic can be exercised on a laptop.
"""
from __future__ import annotations

import math
import threading
import time

from .state import ImuSample, SensorState

G = 9.80665


class ImuReader(threading.Thread):
    def __init__(self, state: SensorState, cfg: dict, sim: bool = False):
        super().__init__(daemon=True)
        self.state = state
        self.cfg = cfg or {}
        self.backend = "sim" if sim else self.cfg.get("backend", "i2c")
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            if self.backend == "sim":
                self._run_sim()
            else:
                self._run_i2c()
        except Exception as exc:  # pragma: no cover
            print(f"[imu] backend '{self.backend}' failed: {exc}; going idle")

    def _run_sim(self):
        t0 = time.time()
        while not self._stop.is_set():
            t = time.time() - t0
            # Mostly at rest; inject a hard-brake around t=20s and a spike at 40s.
            ax = 0.0
            if 20.0 < t < 20.6:
                ax = -0.5 * G           # hard braking
            spike = 3.0 * G if 40.0 < t < 40.05 else 0.0
            self.state.update_imu(ImuSample(
                ts=time.time(), ax=ax, ay=0.0, az=G + spike, gz=0.0))
            time.sleep(0.02)  # 50 Hz

    def _run_i2c(self):  # pragma: no cover - hardware
        from smbus2 import SMBus
        bus_no = int(self.cfg.get("i2c_bus", 1))
        addr = int(self.cfg.get("i2c_addr", 0x28))
        with SMBus(bus_no) as bus:
            while not self._stop.is_set():
                # TEMPLATE: replace with your IMU's linear-accel + gyro registers.
                # For a BNO085 you would read the linear-acceleration and gyro
                # reports (units m/s^2 and rad/s). Placeholder keeps az=G so the
                # rest of the system behaves until you wire the real registers.
                self.state.update_imu(ImuSample(ts=time.time(), az=G))
                time.sleep(0.02)
