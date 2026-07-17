"""Unit tests for the power-watcher debounce logic (pure, no GPIO/hardware).

This is the behavior the whole power subsystem depends on: ignore an engine
crank, but shut down cleanly on a real power loss.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from power_watch import ShutdownDecider


def test_stays_up_while_power_good():
    d = ShutdownDecider(hold_seconds=3.0)
    for t in range(0, 100):
        assert d.update(power_good=True, now=float(t)) is False


def test_crank_dip_does_not_trigger():
    # Power drops for ~1s (engine crank) then recovers; must NOT shut down.
    d = ShutdownDecider(hold_seconds=3.0)
    assert d.update(True, 0.0) is False
    assert d.update(False, 10.0) is False   # power lost
    assert d.update(False, 10.5) is False
    assert d.update(True, 11.0) is False    # recovered within hold window
    # And it must be re-armed: a later sustained loss still triggers.
    assert d.update(False, 20.0) is False
    assert d.update(False, 23.0) is True


def test_sustained_loss_triggers_once():
    d = ShutdownDecider(hold_seconds=3.0)
    assert d.update(True, 0.0) is False
    assert d.update(False, 5.0) is False     # loss begins
    assert d.update(False, 7.9) is False     # not yet past hold
    assert d.update(False, 8.0) is True      # exactly at hold -> fire
    # Fires exactly once; subsequent absent readings do not re-fire.
    assert d.update(False, 9.0) is False
    assert d.update(False, 20.0) is False


def test_recovery_after_fire_rearms():
    d = ShutdownDecider(hold_seconds=2.0)
    assert d.update(False, 0.0) is False
    assert d.update(False, 2.0) is True      # fired
    assert d.update(True, 3.0) is False      # power back -> reset
    assert d.update(False, 10.0) is False
    assert d.update(False, 12.0) is True     # can fire again
