# 01 · Project Plan

## 1. Vision & realistic framing

Build an **edge-AI in-vehicle recorder** that continuously watches the road and
the vehicle's own behavior, automatically detects safety-relevant events and
traffic violations, and saves a short clip (with the seconds *before* the event)
plus structured metadata — timestamp, GPS, speed, violation type, confidence.

The honest positioning: this is a **smart incident dashcam + driver-safety
analytics box**, not a roadside enforcement camera. The most reliable and
legally defensible outputs are:

- **Personal incident evidence** — "the car ahead brake-checked me and I have the
  10 seconds before and after with GPS and speed."
- **Insurance / dispute support** — objective, timestamped record of a collision
  or near miss.
- **Fleet & driver safety coaching** — flag your *own* tailgating, lane
  departures, and hard braking to improve driving.

Detecting *other* drivers' violations (red-light running, speeding, illegal
turns) from a moving platform is technically possible but much lower confidence
and legally weak as enforcement. We build it as **Tier 2/3** with confidence
scores, clearly labeled as advisory, never as citations.

## 2. Success criteria (v1)

| # | Criterion | Target |
| --- | --- | --- |
| S1 | Continuous capture without dropping frames | ≥ 30 fps sustained, < 0.1% dropped |
| S2 | Event clip includes pre-roll | ≥ 10 s before + 10 s after trigger |
| S3 | Tier-1 event precision (collision/hard-brake/lane-departure/tailgating) | ≥ 90% precision on field test set |
| S4 | Evidence integrity | Every clip has matching DB row + GPS + speed + hash |
| S5 | Survives power cycle | Graceful shutdown, no filesystem corruption, auto-start on boot |
| S6 | Thermals | No thermal throttling in 45 °C ambient with active cooling |
| S7 | Plate legibility (when telephoto fitted) | Human-readable plate in ≥ 70% of same-direction daytime captures within 15 m |

## 3. Difficulty tiers (drives the rollout order)

Effort and reliability differ enormously by event type. Build in this order.

**Tier 1 — Ego-vehicle & direct-ahead (easy, high value, do first)**
- Collision / hard impact (IMU spike + optical)
- Hard braking / harsh acceleration / hard cornering (IMU + OBD)
- Lane departure of *own* vehicle (lane detection, forward camera)
- Following-distance / tailgating (detect lead vehicle, estimate time-gap)
- Forward-collision warning / near miss (closing speed to lead vehicle)

**Tier 2 — Scene understanding (moderate)**
- Stop-sign detection + did *we* stop (sign detection + ego speed profile)
- Red-light detection + did *we* enter on red (traffic-light state + stop line)
- Lane-change detection & signal-less lane changes (ours)
- License-plate capture + OCR of nearby vehicles

**Tier 3 — Judging other vehicles (hard, advisory only)**
- Another vehicle running a red light / stop sign (needs their trajectory +
  signal state + stop-line geometry from a moving camera)
- Speeding of other vehicles (monocular relative-speed estimation + ego speed)
- Illegal turns by others (turn-restriction map data required to be meaningful)

## 4. Development phases

Re-ordered from the original spec so that each phase produces something testable
and de-risks the hardest unknowns early.

| Phase | Name | Output | Key risk retired |
| --- | --- | --- | --- |
| 0 | Dev environment & simulation | Pipeline runs on a laptop off recorded video with simulated sensors; unit tests green | Architecture & interfaces |
| 1 | Hardware bring-up | Jetson boots from NVMe, cameras stream, power/ignition-sense works on bench | Power, thermals, camera stack |
| 2 | Capture & storage | Continuous recording to ring buffer + segmented archive; DB schema live | Data integrity, write endurance |
| 3 | Detection & tracking | YOLO + TensorRT + ByteTrack running at target fps on device | Real-time performance |
| 4 | Tier-1 violations | Collision, hard-brake, lane departure, tailgating firing with clips | Core value delivered |
| 5 | Calibration & geometry | Camera-to-ground calibration, distance & speed estimation validated | Measurement accuracy |
| 6 | Tier-2 detections | Signs, signals, ego stop/red-light, ALPR | Scene understanding |
| 7 | Review UI | Local web UI to browse/scrub/export events | Usability |
| 8 | Field testing & tuning | Threshold tuning against real drives; precision/recall report | Real-world robustness |
| 9 | Production enclosure | Vibration-proof, heat-managed, tamper-evident install | Durability |
| 10 | (Optional) Tier-3 + cloud | Advisory other-vehicle detection, cloud sync, fleet | Scale |

## 5. Effort estimate (one experienced developer)

| Phase | Rough effort |
| --- | --- |
| 0 Dev env & sim | 3–5 days |
| 1 Hardware bring-up | 1–2 weeks (parts + debugging) |
| 2 Capture & storage | 1 week |
| 3 Detection & tracking | 1–2 weeks |
| 4 Tier-1 violations | 2 weeks |
| 5 Calibration & geometry | 1–2 weeks |
| 6 Tier-2 detections | 3–4 weeks (models + data) |
| 7 Review UI | 1 week |
| 8 Field testing | ongoing, 2+ weeks concentrated |
| 9 Enclosure | 1 week + iteration |
| **v1 (phases 0–5,7,8)** | **~2–3 months** |
| Full (through Tier-2) | ~4–5 months |

## 6. Budget (single build)

Refined from the original estimate. Full itemized BOM in
[`03-hardware-bom.md`](03-hardware-bom.md).

| Category | Original spec | This plan (recommended) |
| --- | --- | --- |
| Compute (Jetson Orin Nano Super Dev Kit) | $250–500 | ~$249 |
| Cameras (1 wide + 1 global-shutter telephoto) | $50–200 ea | ~$120 + ~$180 |
| Storage (NVMe OS + high-endurance card + USB SSD) | $100–200 | ~$220 |
| Power (automotive DC-DC + supercap + ignition sense) | $30–75 | ~$90 |
| Sensors (GNSS+DR, IMU, OBD-II) | $50–150 | ~$150 |
| Enclosure, cooling, mounts, cabling | $100 | ~$150 |
| **Total (single unit)** | ~$580–1,225 | **~$1,060** |

(The Coral USB TPU from the original spec is intentionally removed — see
[`07-changes-from-original-spec.md`](07-changes-from-original-spec.md).)

## 7. What is done in this repository vs. planned

**Done (in this repo, runnable/testable now):**
- Full architecture and module interfaces
- Config system (`config/config.yaml` + loader)
- Threaded pipeline skeleton with bounded queues
- Camera capture with file/sim fallback
- YOLO detector wrapper (TensorRT-ready), graceful stub if model absent
- Ring-buffer pre/post-event recorder design + implementation
- SQLite evidence store with schema
- Sensor readers (GPS/IMU/OBD) with simulated backends for laptop dev
- Violation rule engine + **working Tier-1 detectors** (collision via IMU,
  hard-brake, tailgating time-gap, lane-departure hook)
- Geometry/calibration helpers
- Unit tests for the rule engine (pure logic, no hardware)

**Planned (stubbed with clear TODOs):**
- Tier-2 sign/signal/red-light logic and ALPR OCR wiring
- Tier-3 other-vehicle advisory detectors
- Review web UI
- Cloud sync / fleet / OTA updates
