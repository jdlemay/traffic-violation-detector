# 02 · Architecture

## 1. System context

```
        ┌──────────────────────── Vehicle ────────────────────────┐
        │                                                          │
  Forward wide cam ─┐                                              │
  Telephoto/ALPR ───┤                                  12V ──► DC-DC (ign. sense)
  (optional) cam   ─┘                                        │  + supercap
        │            │                                       ▼
        ▼            ▼                                   5V/USB-C
   ┌───────────────────────── Jetson Orin Nano Super ─────────────────┐
   │                                                                  │
   │  Cameras → Capture → Detect(YOLO/TensorRT) → Track → Rule engine │
   │                 │                                     │          │
   │              Ring buffer ◄──── trigger ───────────────┘          │
   │                 │                                                │
   │            Recorder → clips  ── Storage(SQLite + files) ── Review UI (local web)
   │                 ▲                                                │
   │   GPS/GNSS+DR ──┤  IMU ──┤  OBD-II ──┤  (sensor fusion)          │
   └──────────────────────────────────────────────────────────────────┘
        │
        ▼
   NVMe (OS) + high-endurance card (buffer) + USB SSD (archive)
```

## 2. Design principles

1. **Decoupled stages, bounded queues.** Capture must never block on inference or
   disk. Each stage runs in its own thread and communicates through fixed-size
   queues that drop the *oldest* frame under back-pressure (never the newest).
2. **Always-on ring buffer.** We continuously encode video into short segments.
   When an event fires, we grab the last *N* seconds already on disk plus the next
   *M* seconds — so we always have pre-roll without re-encoding.
3. **Graceful degradation.** Missing camera → file source. Missing sensor →
   simulated/None. Missing GPU model → detector returns empty detections. The
   whole thing runs on a laptop for development.
4. **Evidence integrity.** Every event = one DB row + one clip + a SHA-256 hash of
   the clip, written atomically-ish (clip finalized, then row committed).
5. **Config over code.** Every threshold, resolution, path, and toggle lives in
   `config/config.yaml`.

## 3. Software architecture (threads & data flow)

```
 CaptureThread(s)            InferenceThread            RulesThread
 ─────────────────           ────────────────           ────────────
 read frame  ──► frame_q ──► detect+track  ──► track_q ──► rule engine
    │                                                        │
    └──► RingBufferWriter (continuous, all frames)           │ event?
                                                             ▼
                                                        EventManager
                                                     ┌───────┴────────┐
                                                 Recorder          Storage
                                              (save clip)      (DB row + hash)

 SensorThread ──► shared SensorState (gps, speed, imu) read by RulesThread
```

- **`frame_q`** (maxsize small, e.g. 4): decouples capture from inference; drops
  oldest on overflow so inference always works on recent frames.
- **`track_q`**: detections+tracks handed to the rule engine.
- **`SensorState`**: a thread-safe latest-value store (GPS fix, speed, IMU
  accel/gyro), updated by the sensor thread, sampled by the rule engine per
  frame. Latest-value semantics (not a queue) because rules want "now".

### Module map (`src/tvd/`)

| Module | Responsibility |
| --- | --- |
| `config.py` | Load/validate YAML into a typed `Config` object |
| `capture.py` | `Camera` (GStreamer/V4L2/file) → frames with timestamps |
| `detector.py` | `Detector` wraps Ultralytics YOLO; TensorRT engine if present |
| `tracker.py` | Multi-object tracking (Ultralytics ByteTrack/BoT-SORT) |
| `geometry.py` | Camera calibration, pixel→ground, distance & speed estimation |
| `recorder.py` | `RingBuffer` (continuous segments) + `ClipRecorder` (event clips) |
| `storage.py` | `EventStore` (SQLite): events, media, sensor snapshots |
| `alpr.py` | Optional plate detection + OCR |
| `sensors/gps.py` | GPS/GNSS reader (gpsd/serial NMEA) + sim |
| `sensors/imu.py` | IMU reader (I²C) + sim |
| `sensors/obd.py` | OBD-II reader (python-OBD) + sim |
| `sensors/state.py` | Thread-safe `SensorState` latest-value store |
| `violations/base.py` | `ViolationDetector` interface + `Event` dataclass |
| `violations/engine.py` | Runs all detectors per frame, dedupes, emits events |
| `violations/*.py` | Individual detectors (collision, tailgating, …) |
| `pipeline.py` | Wires threads, queues, sensors; lifecycle & shutdown |
| `main.py` | CLI entrypoint |

## 4. Event lifecycle

```
1. RulesThread evaluates detectors on (tracks, sensor_state, frame_meta)
2. A detector returns an Event(type, confidence, ...) when its rule fires
3. Engine debounces (per-type cooldown) to avoid duplicate spam
4. EventManager:
     a. asks Recorder to assemble a clip: [t-pre, t+post]
     b. writes still frame(s) at t
     c. computes SHA-256 of finalized clip
     d. inserts row into EventStore with all metadata + media paths + hash
5. (optional) ALPR runs on the still(s) to attach plate text + confidence
6. (optional) event pushed to cloud queue
```

## 5. Data model (SQLite)

```sql
CREATE TABLE events (
  id            INTEGER PRIMARY KEY,
  ts_utc        TEXT NOT NULL,        -- ISO-8601 event time
  type          TEXT NOT NULL,        -- e.g. 'collision','tailgating'
  tier          INTEGER NOT NULL,     -- 1/2/3 difficulty tier
  confidence    REAL NOT NULL,        -- 0..1
  lat           REAL, lon REAL,       -- GPS at event
  speed_mps     REAL,                 -- fused/OBD speed
  heading_deg   REAL,
  clip_path     TEXT,                 -- event video clip
  clip_sha256   TEXT,                 -- integrity hash
  still_path    TEXT,                 -- key frame
  plate_text    TEXT,                 -- optional ALPR
  plate_conf    REAL,
  meta_json     TEXT                  -- detector-specific detail
);
CREATE TABLE sensor_log (             -- optional high-rate breadcrumb
  ts_utc TEXT, lat REAL, lon REAL, speed_mps REAL,
  accel_x REAL, accel_y REAL, accel_z REAL, gyro_z REAL
);
CREATE INDEX idx_events_ts ON events(ts_utc);
CREATE INDEX idx_events_type ON events(type);
```

## 6. Performance budget (Jetson Orin Nano Super, 1080p)

| Stage | Target | Technique |
| --- | --- | --- |
| Capture | 30–60 fps | GStreamer HW pipeline / V4L2, zero-copy where possible |
| Detection | ≥ 30 fps | YOLO11n/s exported to **TensorRT FP16**, batched single stream |
| Tracking | negligible | ByteTrack (CPU-cheap) |
| Encoding | real-time | HW NVENC via GStreamer; never CPU x264 for continuous record |
| Rules | < 1 ms/frame | pure Python on track list |

If detection can't hold 30 fps at full res, options in order of preference:
run detection on every 2nd frame (tracker interpolates), drop model size
(YOLO11s→n), lower detection input resolution (keep record resolution high).

## 7. Failure & safety behavior

- **Power loss:** supercap holds 5V long enough for the ignition-sense line to
  trigger a clean `systemd` shutdown; ring buffer segments are already flushed.
- **Disk full:** archive writer rotates oldest non-flagged segments first;
  flagged event clips are never auto-deleted before the retention window.
- **Thermal:** if the SoC hits a warning temp, drop to detect-every-2nd-frame and
  log a health event rather than crash.
- **Sensor dropout:** rules that require a missing sensor are skipped (and marked
  `degraded` in `meta_json`) rather than firing false events.
