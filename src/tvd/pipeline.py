"""Pipeline orchestrator: wires sensors, capture, detection, the rule engine,
recording and storage together.

Threading model (see docs/02):
  * Sensor threads (gps/imu/obd) update a shared SensorState.
  * The main loop pulls frames, runs detection+tracking, builds a FrameContext,
    runs the rule engine, and dispatches events to the recorder + store.

For clarity this reference implementation runs capture+inference+rules in the
main loop and only the sensors in background threads. Splitting inference into
its own thread with a bounded, drop-oldest queue (as the docs describe) is a
localized change; the interfaces already support it.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Optional

from .capture import open_source
from .config import Config
from .detector import Detector
from .recorder import ClipRecorder, SegmentRingBuffer, SegmentWriter
from .sensors.gps import GpsReader
from .sensors.imu import ImuReader
from .sensors.obd import ObdReader
from .sensors.state import SensorState
from .storage import EventStore
from .violations.base import FrameContext
from .violations.engine import RuleEngine, build_default_detectors


class Pipeline:
    def __init__(self, cfg: Config, source=None, sim_sensors: bool = False,
                 sim_camera: bool = False, max_frames: Optional[int] = None):
        self.cfg = cfg
        self.sim_sensors = sim_sensors
        self.sim_camera = sim_camera
        self.max_frames = max_frames
        self.source = source if source is not None else cfg.get("capture.source", 0)

        # Sensors
        self.state = SensorState()
        self._sensor_threads = []
        if cfg.get("sensors.gps.enabled", True):
            self._sensor_threads.append(
                GpsReader(self.state, cfg.get("sensors.gps", {}), sim=sim_sensors))
        if cfg.get("sensors.imu.enabled", True):
            self._sensor_threads.append(
                ImuReader(self.state, cfg.get("sensors.imu", {}), sim=sim_sensors))
        if cfg.get("sensors.obd.enabled", True):
            self._sensor_threads.append(
                ObdReader(self.state, cfg.get("sensors.obd", {}), sim=sim_sensors))

        # Vision
        det_cfg = dict(cfg.get("detector", {}))
        det_cfg["device"] = cfg.get("system.device", "cpu")
        self.detector = Detector(det_cfg)

        # Rule engine
        vcfg = cfg.get("violations", {})
        self.engine = RuleEngine(
            build_default_detectors(vcfg),
            cooldown_seconds=vcfg.get("cooldown_seconds", 8),
            min_confidence=vcfg.get("min_confidence_to_save", 0.4),
        )

        # Recording + storage
        rc = cfg.get("recorder", {})
        self.ring = SegmentRingBuffer(rc.get("archive_dir", "./data/archive"),
                                      keep_seconds=900.0)
        self.segment_writer = SegmentWriter(
            self.ring, fps=cfg.get("capture.fps", 30),
            segment_seconds=rc.get("segment_seconds", 2))
        self.media_dir = cfg.get("storage.media_dir", "./data/events")
        os.makedirs(self.media_dir, exist_ok=True)
        self.clip_recorder = ClipRecorder(
            self.ring, self.media_dir,
            pre_s=rc.get("pre_event_seconds", 10),
            post_s=rc.get("post_event_seconds", 10),
            container=rc.get("container", "mp4"))
        self.store = EventStore(cfg.get("storage.db_path", "./data/events.db"))

        # Homography (from geometry.fit_ground_homography, stored in config)
        self.homography = None
        H = cfg.get("geometry.homography")
        if H:
            import numpy as np
            self.homography = np.asarray(H, dtype=float)

        self._pending_clips = []  # (fire_at_ts, event_ts, clip_name, event_id)

    def start_sensors(self):
        for t in self._sensor_threads:
            t.start()

    def stop_sensors(self):
        for t in self._sensor_threads:
            t.stop()

    def run(self):
        self.start_sensors()
        cam = open_source(self.source,
                          self.cfg.get("capture.width", 1280),
                          self.cfg.get("capture.height", 720),
                          self.cfg.get("capture.fps", 30),
                          sim=self.sim_camera)
        print(f"[pipeline] running (detector={'on' if self.detector.available() else 'stub'}, "
              f"source={self.source})")
        prev_ts = None
        n = 0
        try:
            for ts, frame in cam.frames():
                h, w = frame.shape[:2]
                self.segment_writer.write(ts, frame)
                tracks = self.detector.track(frame)
                dt = 0.0 if prev_ts is None else ts - prev_ts
                prev_ts = ts
                ctx = FrameContext(ts=ts, frame_w=w, frame_h=h, tracks=tracks,
                                   sensors=self.state.snapshot(),
                                   homography=self.homography, dt=dt)
                for ev in self.engine.process(ctx):
                    self._on_event(ev, ctx, frame)
                self._flush_pending_clips(ts)
                n += 1
                if self.max_frames and n >= self.max_frames:
                    break
        finally:
            self.segment_writer.close(prev_ts)
            cam.release()
            self.stop_sensors()
            self.store.close()
            print(f"[pipeline] stopped after {n} frames")

    def _on_event(self, ev, ctx, frame):
        snap = ctx.sensors
        speed = snap.best_speed_mps()
        stamp = f"{datetime.fromtimestamp(ev.ts, tz=timezone.utc):%Y%m%dT%H%M%S}"
        still_path = self._save_still(frame, f"{stamp}_{ev.type}")
        eid = self.store.record(ev, gps=snap.gps, speed_mps=speed,
                                heading_deg=snap.gps.heading_deg,
                                still_path=still_path)
        # Schedule clip assembly for after the post-roll window has elapsed;
        # carry the ORIGINAL event ts so a late flush can't shift the window.
        fire_at = ev.ts + self.clip_recorder.post_s + 0.5
        self._pending_clips.append((fire_at, ev.ts, f"{stamp}_{ev.type}_{eid}", eid))
        print(f"[event] #{eid} {ev.type} conf={ev.confidence:.2f} "
              f"{'(degraded) ' if ev.degraded else ''}meta={ev.meta}")

    def _save_still(self, frame, name):
        try:
            import cv2
            path = os.path.join(self.media_dir, f"{name}.jpg")
            cv2.imwrite(path, frame)
            return path
        except Exception:
            return None

    def _flush_pending_clips(self, now_ts):
        still, ready = [], []
        for item in self._pending_clips:
            (ready if item[0] <= now_ts else still).append(item)
        self._pending_clips = still
        for _, event_ts, name, eid in ready:
            clip = self.clip_recorder.assemble(event_ts, name)
            if clip:
                self.store.update_clip(eid, clip)
