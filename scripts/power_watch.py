#!/usr/bin/env python3
"""Ignition-sense power watcher — triggers a clean shutdown on power loss.

Wiring (see docs/08 Stage 5): the vehicle ignition/ACC line, or a supercap
DC-UPS "power-good" (PGOOD) output, is level-shifted (optocoupler or resistor
divider) into a Jetson GPIO. This watcher reads that GPIO; when input power has
been gone for longer than the hold window (long enough to ignore an engine-crank
dip), it runs `shutdown` so the OS halts cleanly while the supercapacitor is
still carrying the 5 V rail — protecting the filesystem and the last clip.

The decision logic (`ShutdownDecider`) is pure and unit-tested. The GPIO layer
uses Jetson.GPIO when present and is skipped otherwise, so this file imports and
tests fine on any machine.
"""
from __future__ import annotations

import argparse
import subprocess
import time


class ShutdownDecider:
    """Debounced power-loss decision.

    `power_good=True` means input power is present. Returns True exactly once,
    when power has been continuously absent for `hold_seconds` — the caller then
    initiates shutdown. A momentary dip (crank) that recovers resets the timer
    and never triggers.
    """

    def __init__(self, hold_seconds: float = 3.0):
        self.hold_seconds = float(hold_seconds)
        self._lost_since: float | None = None
        self._fired = False

    def update(self, power_good: bool, now: float) -> bool:
        if power_good:
            self._lost_since = None
            self._fired = False
            return False
        if self._lost_since is None:
            self._lost_since = now
        if not self._fired and (now - self._lost_since) >= self.hold_seconds:
            self._fired = True
            return True
        return False


def _read_gpio_factory(pin: int, active_low: bool):
    """Return a callable() -> power_good bool, or raise if GPIO is unavailable."""
    import Jetson.GPIO as GPIO  # type: ignore
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(pin, GPIO.IN)

    def read() -> bool:
        level = GPIO.input(pin)
        # active_low: a LOW level means power-good (e.g. PGOOD pulled low when OK)
        return (level == 0) if active_low else (level == 1)

    return read


def run(pin: int, hold_seconds: float, poll_seconds: float, active_low: bool,
        dry_run: bool = False) -> None:
    decider = ShutdownDecider(hold_seconds)
    try:
        read_power_good = _read_gpio_factory(pin, active_low)
    except Exception as exc:  # pragma: no cover - device only
        print(f"[power_watch] GPIO unavailable ({exc}); exiting. "
              f"Install Jetson.GPIO and run on the device.")
        return
    print(f"[power_watch] watching pin {pin} (hold={hold_seconds}s, "
          f"active_low={active_low})")
    while True:
        good = read_power_good()
        if decider.update(good, time.monotonic()):
            print("[power_watch] input power lost — initiating clean shutdown")
            if not dry_run:
                subprocess.run(["/sbin/shutdown", "-h", "now"], check=False)
            return
        time.sleep(poll_seconds)


def main(argv=None):
    p = argparse.ArgumentParser(description="Ignition-sense power watcher")
    p.add_argument("--pin", type=int, default=7, help="BOARD pin number to read")
    p.add_argument("--hold-seconds", type=float, default=3.0,
                   help="power must be gone this long before shutdown")
    p.add_argument("--poll-seconds", type=float, default=0.2)
    p.add_argument("--active-low", action="store_true",
                   help="LOW level means power-good (default: HIGH means good)")
    p.add_argument("--dry-run", action="store_true",
                   help="log the decision but do not actually shut down")
    args = p.parse_args(argv)
    run(args.pin, args.hold_seconds, args.poll_seconds, args.active_low,
        dry_run=args.dry_run)


if __name__ == "__main__":
    main()
