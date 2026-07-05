"""Tier-1: tailgating (following distance) and forward-collision (TTC).

Selects the in-lane lead vehicle, estimates its distance from the bbox
ground-contact point via the calibrated homography (or pinhole fallback),
then computes the following time-gap and the time-to-collision from the
distance's rate of change combined with ego speed.

Requires ego speed (OBD/GPS). Without calibration OR speed it degrades: it
still reports a persistent close lead using bbox size as a proxy, but marks the
event `degraded` with lower confidence.
"""
from __future__ import annotations

from typing import Optional

from .. import geometry
from .base import Event, FrameContext, Track, ViolationDetector

VEHICLE_LABELS = {"car", "truck", "bus", "motorcycle"}


class TailgatingDetector(ViolationDetector):
    type = "tailgating"
    tier = 1

    def __init__(self, cfg):
        super().__init__(cfg)
        self.time_gap = float(self.cfg.get("time_gap_seconds", 1.0))
        self.hold = float(self.cfg.get("hold_seconds", 2.0))
        self.min_speed = float(self.cfg.get("min_ego_speed_mps", 8.0))
        self.ttc_warn = float(self.cfg.get("ttc_seconds", 1.5))
        # temporal state
        self._below_since: Optional[float] = None
        self._prev_dist: Optional[float] = None
        self._prev_ts: Optional[float] = None

    def _select_lead(self, ctx: FrameContext) -> Optional[Track]:
        """The vehicle whose center is nearest the image center-x and lowest
        (closest) in the frame — a simple in-lane, nearest-ahead heuristic."""
        cx0 = ctx.frame_w / 2.0
        lane_tol = ctx.frame_w * 0.18
        candidates = [
            t for t in ctx.tracks
            if t.label in VEHICLE_LABELS and abs(t.cx - cx0) < lane_tol
        ]
        if not candidates:
            return None
        # lowest bottom edge (largest y2) = nearest ahead
        return max(candidates, key=lambda t: t.bbox[3])

    def update(self, ctx: FrameContext) -> Optional[Event]:
        speed = ctx.sensors.best_speed_mps()
        if speed is not None and speed < self.min_speed:
            self._reset()
            return None

        lead = self._select_lead(ctx)
        if lead is None:
            self._reset()
            return None

        # Estimate distance (m). None if underdetermined.
        dist = geometry.distance_to_bbox_ground(
            ctx.homography, lead.bbox, image_height=ctx.frame_h,
        )

        degraded = dist is None or speed is None
        gap = None
        ttc = None
        if not degraded:
            gap = geometry.time_gap_seconds(dist, speed)
            # closing speed from distance derivative
            if self._prev_dist is not None and self._prev_ts is not None:
                dt = max(1e-3, ctx.ts - self._prev_ts)
                closing = (self._prev_dist - dist) / dt
                ttc = geometry.time_to_collision(dist, closing)
            self._prev_dist, self._prev_ts = dist, ctx.ts

        # Forward-collision takes priority (more urgent) if TTC is low.
        if ttc is not None and ttc < self.ttc_warn:
            return Event(
                type="forward_collision",
                tier=1,
                confidence=min(1.0, 0.6 + lead.conf * 0.4),
                ts=ctx.ts,
                meta={"ttc_s": round(ttc, 2), "distance_m": round(dist, 1)},
            )

        # Tailgating: time-gap below threshold, sustained.
        below = (gap is not None and gap < self.time_gap) or (
            degraded and self._proximity_proxy(lead, ctx) )
        if not below:
            self._below_since = None
            return None

        if self._below_since is None:
            self._below_since = ctx.ts
        if ctx.ts - self._below_since < self.hold:
            return None  # not sustained yet

        conf = 0.5 if degraded else min(1.0, 0.6 + (self.time_gap - (gap or 0)))
        meta = {"time_gap_s": round(gap, 2) if gap is not None else None,
                "distance_m": round(dist, 1) if dist is not None else None,
                "lead_track_id": lead.track_id}
        return Event(self.type, self.tier, conf, ts=ctx.ts, meta=meta,
                     degraded=degraded)

    def _proximity_proxy(self, lead: Track, ctx: FrameContext) -> bool:
        """Fallback when distance is unknown: a lead vehicle occupying a large
        fraction of the lower-central frame is 'close'."""
        return lead.bbox[3] > ctx.frame_h * 0.85 and lead.area > (
            0.06 * ctx.frame_w * ctx.frame_h)

    def _reset(self) -> None:
        self._below_since = None
        self._prev_dist = None
        self._prev_ts = None
