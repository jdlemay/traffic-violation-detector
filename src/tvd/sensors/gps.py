"""GPS/GNSS reader.

Backends:
  * gpsd   — read from a running gpsd (recommended on device).
  * serial — parse raw NMEA from a serial port with pynmea2.
  * sim    — synthesize a fix (constant speed) for laptop dev.

Runs in its own thread, pushing GpsFix into the shared SensorState.
"""
from __future__ import annotations

import threading
import time

from .state import GpsFix, SensorState

KNOTS_TO_MPS = 0.514444


class GpsReader(threading.Thread):
    def __init__(self, state: SensorState, cfg: dict, sim: bool = False):
        super().__init__(daemon=True)
        self.state = state
        self.cfg = cfg or {}
        self.backend = "sim" if sim else self.cfg.get("backend", "gpsd")
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            if self.backend == "sim":
                self._run_sim()
            elif self.backend == "serial":
                self._run_serial()
            else:
                self._run_gpsd()
        except Exception as exc:  # pragma: no cover
            print(f"[gps] backend '{self.backend}' failed: {exc}; going idle")

    def _run_sim(self):
        # Straight line at ~15 m/s heading north from a fixed origin.
        lat, lon = 39.2904, -76.6122  # Baltimore, MD
        while not self._stop.is_set():
            lat += 15.0 / 111_111.0
            self.state.update_gps(GpsFix(ts=time.time(), lat=lat, lon=lon,
                                         speed_mps=15.0, heading_deg=0.0,
                                         valid=True))
            time.sleep(1.0)

    def _run_serial(self):  # pragma: no cover - hardware
        import pynmea2
        import serial
        port = self.cfg.get("serial_port", "/dev/ttyACM0")
        baud = int(self.cfg.get("baud", 38400))
        with serial.Serial(port, baud, timeout=1) as ser:
            while not self._stop.is_set():
                line = ser.readline().decode("ascii", errors="replace").strip()
                if not line.startswith("$"):
                    continue
                try:
                    msg = pynmea2.parse(line)
                except pynmea2.ParseError:
                    continue
                if getattr(msg, "sentence_type", "") == "RMC" and msg.status == "A":
                    spd = float(msg.spd_over_grnd or 0) * KNOTS_TO_MPS
                    self.state.update_gps(GpsFix(
                        ts=time.time(), lat=msg.latitude, lon=msg.longitude,
                        speed_mps=spd,
                        heading_deg=float(msg.true_course or 0) or None,
                        valid=True))

    def _run_gpsd(self):  # pragma: no cover - hardware
        import gps  # python3-gps
        session = gps.gps(mode=gps.WATCH_ENABLE | gps.WATCH_NEWSTYLE)
        while not self._stop.is_set():
            report = session.next()
            if getattr(report, "class", "") == "TPV" and getattr(report, "mode", 0) >= 2:
                self.state.update_gps(GpsFix(
                    ts=time.time(),
                    lat=getattr(report, "lat", None),
                    lon=getattr(report, "lon", None),
                    speed_mps=getattr(report, "speed", None),
                    heading_deg=getattr(report, "track", None),
                    valid=True))
