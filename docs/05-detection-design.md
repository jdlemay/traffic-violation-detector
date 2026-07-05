# 05 · Detection Design (per-violation) & Calibration

For each event: **inputs → method → trigger condition → confidence → failure
modes**. Difficulty tier in brackets. Tier-1 detectors have working code in
`src/tvd/violations/`; Tier-2/3 are specified here and stubbed in code.

## Calibration (prerequisite for anything measuring distance/speed)

Distance and speed estimates require a **camera-to-ground homography**. One-time
per install:

1. Fix the camera pose (mount locked).
2. Place markers at known ground distances ahead (e.g. 5, 10, 20, 30 m) along the
   lane, or drive past lane dashes of known length (US: 10 ft line + 30 ft gap).
3. Solve the homography mapping image points on the road plane to ground
   coordinates (`geometry.py::fit_ground_homography`).
4. Validate: predicted distance to a known object vs. tape measure < 10% error.

With ego speed from OBD/GNSS, relative distance over time → closing speed, which
powers tailgating and forward-collision logic. This is the flat-road
approximation; hills and pitch introduce error (bounded by IMU pitch).

---

## Tier 1 — reliable, ego-centric

### Collision / hard impact  `[T1]`
- **Inputs:** IMU (accel magnitude), optional optical.
- **Method:** detect an acceleration spike exceeding a g-threshold sustained
  over a few ms; corroborate with a sudden speed drop (OBD) if available.
- **Trigger:** `|a| − 1g_gravity_removed > COLLISION_G` (default ~2.5 g).
- **Confidence:** scales with peak g and corroboration.
- **Failures:** pothole/speed-bump false positives → require sustained/high g and
  optionally optical corroboration; tune per vehicle.

### Hard braking / harsh accel / hard cornering  `[T1]`
- **Inputs:** IMU longitudinal/lateral accel (and OBD speed derivative).
- **Method:** thresholded longitudinal deceleration / lateral accel.
- **Trigger:** `a_long < −HARD_BRAKE` (e.g. −0.4 g) etc.
- **Use:** driver coaching, and as a pre-trigger to keep the buffer around
  near-misses.

### Tailgating / following distance  `[T1]`
- **Inputs:** forward detections (lead vehicle bbox), homography, ego speed.
- **Method:** identify the in-lane lead vehicle, estimate distance via
  homography (bbox ground-contact point), compute **time gap** = distance / ego
  speed.
- **Trigger:** `time_gap < TAILGATE_SEC` (e.g. 1.0 s) sustained > `T_HOLD`.
- **Confidence:** from detection score + distance stability.
- **Failures:** wrong lead selection on curves; require lane association and
  temporal persistence.

### Forward-collision / near miss  `[T1]`
- **Inputs:** lead-vehicle distance over time (closing speed), ego speed.
- **Method:** time-to-collision `TTC = distance / closing_speed`.
- **Trigger:** `TTC < TTC_WARN` (e.g. 1.5 s) with positive closing speed.

### Lane departure (own vehicle)  `[T1]`
- **Inputs:** forward camera lane lines.
- **Method:** detect left/right lane markings (classic CV to start), track the
  vehicle's offset from lane center; flag crossing without turn signal (turn
  signal from OBD if exposed).
- **Trigger:** lane-line crossing with lateral velocity toward it, no signal.
- **Failures:** faded lines, rain, glare → confidence gating + persistence.

---

## Tier 2 — scene understanding

### Stop-sign compliance (own vehicle)  `[T2]`
- **Inputs:** YOLO `stop sign` detections (grows as we approach), ego speed
  profile, GPS.
- **Method:** when a stop sign is detected ahead and grows past a size threshold
  (we're at the line), check whether ego speed reached ~0 within a window.
- **Trigger:** approached a stop sign but `min(speed)` stayed above a small
  threshold → "rolling stop".
- **Failures:** distinguishing which sign applies to us; use bbox growth + lane.

### Red-light entry (own vehicle)  `[T2]`
- **Inputs:** `traffic light` detections + **state classification**
  (red/yellow/green via color/region classifier on the light crop), stop-line
  position, ego speed.
- **Method:** track the relevant signal's state; if state == red while ego
  crosses the stop line moving forward → violation.
- **Failures:** which light governs our lane; sun glare washing out color;
  requires a light-state classifier (small CNN on the crop).

### Lane-change / signal-less lane change (own)  `[T2]`
- **Inputs:** lane offset trajectory + turn-signal (OBD).
- **Method:** detect lateral transition across a lane line; check signal state in
  the seconds prior.

### License-plate capture + OCR  `[T2]`
- **Inputs:** telephoto (global-shutter) frames, vehicle detections.
- **Method:** plate-detector YOLO on vehicle crops → deskew → OCR
  (`fast-plate-ocr`/PaddleOCR). Attach text + confidence to the event.
- **Failures:** motion blur (mitigated by global shutter), angle, dirt, night.
  Store the crop even when OCR is low-confidence for human review.

---

## Tier 3 — judging other vehicles (advisory only)

> These are **low-confidence, advisory** outputs. Never treat as citations.
> They require estimating another vehicle's trajectory and the governing signal
> state from a moving platform — inherently noisy.

### Other vehicle runs red light / stop sign  `[T3]`
- **Inputs:** tracked other-vehicle trajectory, signal/sign state, stop-line
  geometry, cross-street inference.
- **Method:** associate a vehicle's path with a controlled approach and detect it
  entering the intersection against a red/without stopping.
- **Reality:** requires reliable stop-line and signal-to-lane association from
  outside the vehicle — fragile. Ship with heavy confidence discounting.

### Other-vehicle speeding  `[T3]`
- **Inputs:** tracked vehicle distance over time (homography), ego speed, time.
- **Method:** relative speed from distance derivative + ego speed = absolute
  speed; compare to a speed-limit source (map/manual).
- **Reality:** monocular distance error compounds into speed error; treat as a
  rough estimate with wide error bars. A radar module would be the real fix.

### Illegal turns (others)  `[T3]`
- Requires turn-restriction map data (OSM turn restrictions) to be meaningful;
  otherwise you can only detect *a* turn, not an *illegal* one.

---

## Confidence & debouncing (applies to all)

- Every detector returns `confidence ∈ [0,1]`; the engine records it and can
  gate saving below a per-type threshold.
- Per-type **cooldown** prevents one continuous condition (e.g. sustained
  tailgating) from emitting hundreds of events — one event per cooldown window,
  with `meta_json.duration` capturing how long it persisted.
- Detectors requiring a missing sensor mark the event `degraded` and lower
  confidence rather than firing blind.
