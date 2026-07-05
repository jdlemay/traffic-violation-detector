"""OBD-II reader (python-OBD).

Backends:
  * obd — connect to an ELM327/STN adapter and poll SPEED/RPM/THROTTLE.
  * sim — synthesize a speed trace (accelerate, cruise, then a hard-brake dip)
    aligned with the IMU sim so tailgating/collision logic has real numbers.

OBD wheel speed is the *primary* ego-speed source (see docs/07).
"""
from __future__ import annotations

import threading
import time

from .state import ObdSample, SensorState

KMH_TO_MPS = 1000.0 / 3600.0


class ObdReader(threading.Thread):
    def __init__(self, state: SensorState, cfg: dict, sim: bool = False):
        super().__init__(daemon=True)
        self.state = state
        self.cfg = cfg or {}
        self.backend = "sim" if sim else self.cfg.get("backend", "obd")
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            if self.backend == "sim":
                self._run_sim()
            else:
                self._run_obd()
        except Exception as exc:  # pragma: no cover
            print(f"[obd] backend '{self.backend}' failed: {exc}; going idle")

    def _run_sim(self):
        t0 = time.time()
        while not self._stop.is_set():
            t = time.time() - t0
            if t < 10:
                speed = min(15.0, 1.5 * t)      # accelerate to ~15 m/s
            elif t < 20:
                speed = 15.0                     # cruise
            elif t < 20.6:
                speed = max(0.0, 15.0 - 25.0 * (t - 20))  # hard brake
            else:
                speed = 8.0
            self.state.update_obd(ObdSample(ts=time.time(), speed_mps=speed))
            time.sleep(0.1)  # 10 Hz

    def _run_obd(self):  # pragma: no cover - hardware
        import obd
        port = self.cfg.get("port")  # None => auto-detect
        conn = obd.OBD(portstr=port) if port else obd.OBD()
        while not self._stop.is_set():
            spd = conn.query(obd.commands.SPEED)
            rpm = conn.query(obd.commands.RPM)
            thr = conn.query(obd.commands.THROTTLE_POS)
            speed_mps = None
            if spd is not None and not spd.is_null():
                speed_mps = float(spd.value.to("km/h").magnitude) * KMH_TO_MPS
            self.state.update_obd(ObdSample(
                ts=time.time(), speed_mps=speed_mps,
                rpm=(None if rpm is None or rpm.is_null() else float(rpm.value.magnitude)),
                throttle=(None if thr is None or thr.is_null() else float(thr.value.magnitude)),
            ))
            time.sleep(0.1)
