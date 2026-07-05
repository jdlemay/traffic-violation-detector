"""The rule engine: runs all enabled detectors each frame, applies confidence
gating and per-type cooldown debouncing, and yields the surviving events.

Cross-detector concerns (cooldown, min confidence) live here so individual
detectors stay simple and pure.
"""
from __future__ import annotations

from typing import Iterable, Optional

from .base import Event, FrameContext, ViolationDetector
from .collision import CollisionDetector
from .hard_brake import HarshDrivingDetector
from .lane_departure import LaneDepartureDetector
from .tailgating import TailgatingDetector


def build_default_detectors(vcfg: dict, lane_extractor=None) -> list[ViolationDetector]:
    """Instantiate the Tier-1 detectors from the `violations` config section."""
    detectors: list[ViolationDetector] = []
    if vcfg.get("collision", {}).get("enabled", True):
        detectors.append(CollisionDetector(vcfg.get("collision", {})))
    if vcfg.get("hard_brake", {}).get("enabled", True):
        detectors.append(HarshDrivingDetector(vcfg.get("hard_brake", {})))
    if vcfg.get("tailgating", {}).get("enabled", True):
        tcfg = dict(vcfg.get("tailgating", {}))
        tcfg["ttc_seconds"] = vcfg.get("forward_collision", {}).get("ttc_seconds", 1.5)
        detectors.append(TailgatingDetector(tcfg))
    if vcfg.get("lane_departure", {}).get("enabled", True):
        detectors.append(LaneDepartureDetector(vcfg.get("lane_departure", {}),
                                               lane_extractor=lane_extractor))
    # Tier-2/3 detectors (stop_sign, red_light, other_vehicle_speeding) are
    # specified in docs/05 and can be appended here as they are implemented.
    return detectors


class RuleEngine:
    def __init__(self, detectors: Iterable[ViolationDetector],
                 cooldown_seconds: float = 8.0,
                 min_confidence: float = 0.4):
        self.detectors = [d for d in detectors if d.enabled]
        self.cooldown = float(cooldown_seconds)
        self.min_conf = float(min_confidence)
        self._last_fired: dict[str, float] = {}

    def process(self, ctx: FrameContext) -> list[Event]:
        """Run all detectors, return events that pass gating + cooldown."""
        out: list[Event] = []
        for det in self.detectors:
            try:
                ev = det.update(ctx)
            except Exception:  # a detector must never take down the pipeline
                # In production, log with traceback + a health counter.
                continue
            surviving = self._admit(ev)
            if surviving is not None:
                out.append(surviving)
        return out

    def _admit(self, ev: Optional[Event]) -> Optional[Event]:
        if ev is None or ev.confidence < self.min_conf:
            return None
        last = self._last_fired.get(ev.type)
        if last is not None and (ev.ts - last) < self.cooldown:
            return None
        self._last_fired[ev.type] = ev.ts
        return ev
