"""Unit tests for the rule engine and Tier-1 detectors — pure logic, no
hardware, no models, no GPU. This is the core value that can be validated on
any machine.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tvd.sensors.state import (GpsFix, ImuSample, ObdSample, SensorSnapshot)
from tvd.violations.base import Event, FrameContext, Track
from tvd.violations.collision import CollisionDetector
from tvd.violations.hard_brake import HarshDrivingDetector
from tvd.violations.tailgating import TailgatingDetector
from tvd.violations.engine import RuleEngine

G = 9.80665


def snap(*, ax=0.0, ay=0.0, az=G, speed=None, prev_speed=None):
    return SensorSnapshot(
        gps=GpsFix(ts=0, valid=speed is not None, speed_mps=speed),
        imu=ImuSample(ts=0, ax=ax, ay=ay, az=az),
        obd=ObdSample(ts=0, speed_mps=speed),
    )


def ctx(ts, snapshot, tracks=None, w=1280, h=720, H=None):
    return FrameContext(ts=ts, frame_w=w, frame_h=h, tracks=tracks or [],
                        sensors=snapshot, homography=H)


# ---------------- Collision ----------------

def test_collision_fires_on_big_spike():
    det = CollisionDetector({"threshold_g": 2.5})
    ev = det.update(ctx(1.0, snap(az=G + 3.0 * G, speed=15)))
    assert ev is not None and ev.type == "collision"
    assert ev.confidence > 0.5


def test_collision_ignores_normal_driving():
    det = CollisionDetector({"threshold_g": 2.5})
    assert det.update(ctx(1.0, snap(ax=-0.3 * G, speed=15))) is None


def test_collision_confidence_boosted_by_speed_drop():
    det = CollisionDetector({"threshold_g": 2.5, "corroborate_speed_drop_mps": 3.0})
    det.update(ctx(1.0, snap(az=G, speed=15)))          # establish prior speed
    ev = det.update(ctx(1.1, snap(az=G + 3.0 * G, speed=5)))  # spike + big drop
    assert ev is not None and ev.meta["corroborated_by_speed"] is True


# ---------------- Harsh driving ----------------

def test_hard_brake_detected():
    det = HarshDrivingDetector({"decel_g": 0.4})
    ev = det.update(ctx(1.0, snap(ax=-0.5 * G)))
    assert ev is not None and ev.meta["kind"] == "hard_brake"


def test_hard_corner_detected():
    det = HarshDrivingDetector({"lateral_g": 0.45})
    ev = det.update(ctx(1.0, snap(ay=0.6 * G)))
    assert ev is not None and ev.meta["kind"] == "hard_corner"


def test_gentle_driving_no_event():
    det = HarshDrivingDetector({})
    assert det.update(ctx(1.0, snap(ax=-0.2 * G, ay=0.1 * G))) is None


# ---------------- Tailgating (proximity-proxy path, no homography) ----------------

def _close_lead(w=1280, h=720):
    # A large vehicle bbox low-and-central: proximity proxy should flag it.
    return Track(track_id=7, cls=2, label="car", conf=0.9,
                 bbox=(w * 0.35, h * 0.4, w * 0.65, h * 0.98))


def test_tailgating_needs_persistence_then_fires():
    det = TailgatingDetector({"time_gap_seconds": 1.0, "hold_seconds": 2.0,
                              "min_ego_speed_mps": 8.0})
    lead = _close_lead()
    # First frame: below threshold but not yet sustained.
    assert det.update(ctx(100.0, snap(speed=15), [lead])) is None
    # After the hold window: fires (degraded, since no homography/distance).
    ev = det.update(ctx(102.5, snap(speed=15), [lead]))
    assert ev is not None and ev.type == "tailgating" and ev.degraded


def test_tailgating_suppressed_at_low_speed():
    det = TailgatingDetector({"min_ego_speed_mps": 8.0})
    ev = det.update(ctx(100.0, snap(speed=3), [_close_lead()]))
    assert ev is None


# ---------------- Engine: gating + cooldown ----------------

class _AlwaysFire:
    enabled = True
    type = "x"

    def __init__(self, conf):
        self._conf = conf

    def update(self, ctx):
        return Event(type="x", tier=1, confidence=self._conf, ts=ctx.ts)


def test_engine_gates_low_confidence():
    eng = RuleEngine([_AlwaysFire(0.2)], min_confidence=0.4)
    assert eng.process(ctx(1.0, snap())) == []


def test_engine_cooldown_dedupes():
    eng = RuleEngine([_AlwaysFire(0.9)], cooldown_seconds=8, min_confidence=0.4)
    first = eng.process(ctx(1.0, snap()))
    within = eng.process(ctx(3.0, snap()))     # inside cooldown
    after = eng.process(ctx(12.0, snap()))     # past cooldown
    assert len(first) == 1 and within == [] and len(after) == 1


def test_engine_survives_detector_exception():
    class Boom:
        enabled = True
        type = "boom"
        def update(self, ctx):
            raise RuntimeError("detector blew up")
    eng = RuleEngine([Boom(), _AlwaysFire(0.9)], min_confidence=0.4)
    out = eng.process(ctx(1.0, snap()))
    assert len(out) == 1 and out[0].type == "x"
