"""Unit tests for the Tier-2 detectors: stop-sign compliance and red-light
entry. Pure logic — no hardware, no models."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tvd.sensors.state import GpsFix, ImuSample, ObdSample, SensorSnapshot
from tvd.violations.base import FrameContext, Track
from tvd.violations.red_light import LightState, RedLightEntryDetector
from tvd.violations.stop_sign import StopSignComplianceDetector

W, H = 1280, 720


def snap(speed=None):
    return SensorSnapshot(
        gps=GpsFix(ts=0, valid=speed is not None, speed_mps=speed),
        imu=ImuSample(ts=0),
        obd=ObdSample(ts=0, speed_mps=speed),
    )


def ctx(ts, speed=None, tracks=None, light=None):
    c = FrameContext(ts=ts, frame_w=W, frame_h=H, tracks=tracks or [],
                     sensors=snap(speed))
    if light is not None:
        c.light_state = light
    return c


def stop_sign(area_frac):
    # Build a stop-sign track whose bbox area is `area_frac` of the frame.
    side = (area_frac * W * H) ** 0.5
    return Track(track_id=1, cls=11, label="stop sign", conf=0.9,
                 bbox=(100, 100, 100 + side, 100 + side))


def _drive_past_sign(det, speeds, area=0.01, start=100.0, dt=0.1):
    """Feed frames with a large sign present at each `speeds[i]`, then frames
    with no sign so the detector concludes we've passed it. Returns the event."""
    t = start
    for s in speeds:
        det.update(ctx(t, speed=s, tracks=[stop_sign(area)]))
        t += dt
    # Sign gone; wait past lost_seconds, then a final tick to evaluate.
    ev = None
    for _ in range(12):
        ev = det.update(ctx(t, speed=speeds[-1], tracks=[]))
        if ev is not None:
            break
        t += dt
    return ev


def test_stop_sign_rolling_stop_flagged():
    det = StopSignComplianceDetector({"stop_speed_mps": 0.5, "enter_area_frac": 0.004})
    # Never drops below ~4 m/s at the line -> rolling stop.
    ev = _drive_past_sign(det, [10, 8, 6, 5, 4, 5, 8])
    assert ev is not None and ev.type == "stop_sign_violation"
    assert ev.meta["kind"] == "rolling_stop"
    assert ev.meta["min_speed_mps"] >= 4.0


def test_stop_sign_full_stop_not_flagged():
    det = StopSignComplianceDetector({"stop_speed_mps": 0.5, "enter_area_frac": 0.004})
    # Comes to a full stop (0.0) at the line -> compliant, no event.
    ev = _drive_past_sign(det, [10, 6, 3, 1, 0.0, 2, 6])
    assert ev is None


def test_stop_sign_inert_without_speed():
    det = StopSignComplianceDetector({"enter_area_frac": 0.004})
    ev = _drive_past_sign(det, [None, None, None])
    assert ev is None


def test_stop_sign_ignores_distant_sign():
    # A tiny (distant) sign never crosses the enter-area threshold.
    det = StopSignComplianceDetector({"enter_area_frac": 0.01})
    t = 100.0
    for _ in range(5):
        assert det.update(ctx(t, speed=10, tracks=[stop_sign(0.0005)])) is None
        t += 0.1


# ---------------- Red light ----------------

def test_red_light_entry_flagged():
    det = RedLightEntryDetector({})
    light = LightState(color="red", governing=True, crossing_stop_line=True)
    ev = det.update(ctx(1.0, speed=12, light=light))
    assert ev is not None and ev.type == "red_light_violation"
    assert ev.meta["light_color"] == "red"


def test_green_light_not_flagged():
    det = RedLightEntryDetector({})
    light = LightState(color="green", governing=True, crossing_stop_line=True)
    assert det.update(ctx(1.0, speed=12, light=light)) is None


def test_red_but_not_crossing_not_flagged():
    det = RedLightEntryDetector({})
    light = LightState(color="red", governing=True, crossing_stop_line=False)
    assert det.update(ctx(1.0, speed=12, light=light)) is None


def test_red_but_stopped_not_flagged():
    det = RedLightEntryDetector({"min_speed_mps": 1.0})
    light = LightState(color="red", governing=True, crossing_stop_line=True)
    assert det.update(ctx(1.0, speed=0.0, light=light)) is None


def test_red_light_degraded_without_speed():
    det = RedLightEntryDetector({})
    light = LightState(color="red", governing=True, crossing_stop_line=True)
    ev = det.update(ctx(1.0, speed=None, light=light))
    assert ev is not None and ev.degraded and ev.confidence < 0.85


def test_red_light_inert_without_state():
    det = RedLightEntryDetector({})
    assert det.update(ctx(1.0, speed=12)) is None  # no light_state injected
