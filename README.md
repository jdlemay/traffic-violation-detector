# Traffic Violation Detection System (TVDS)

[![CI](https://github.com/jdlemay/traffic-violation-detector/actions/workflows/ci.yml/badge.svg)](https://github.com/jdlemay/traffic-violation-detector/actions/workflows/ci.yml)

An AI-powered, in-vehicle edge system that detects dangerous driving and traffic
violations from onboard cameras and vehicle sensors, then records timestamped,
GPS-tagged evidence for later review.

Think of it as a **smart dashcam with an incident brain**: it is always watching,
but only saves and flags the moments that matter (hard braking, tailgating, a
vehicle running a stop sign in front of you, your own lane departures, near
misses), with a short buffer of video from *before* each event.

> **Read this first:** This project records other people's driving on public
> roads and can read license plates. That carries real legal and privacy
> obligations, and the value of the evidence depends heavily on how it is
> captured and stored. See [`docs/06-legal-and-privacy.md`](docs/06-legal-and-privacy.md)
> before deploying anything. The realistic, defensible use cases are **personal
> incident evidence, insurance/dispute support, and fleet safety coaching** —
> *not* citizen traffic enforcement.

---

## What changed from the original spec (and why)

I kept the goal but re-engineered several choices for reliability, cost, and
buildability. Full rationale in
[`docs/07-changes-from-original-spec.md`](docs/07-changes-from-original-spec.md).
The headlines:

| Area | Original spec | Recommended change | Why |
| --- | --- | --- | --- |
| Compute | Jetson Orin Nano Dev Kit | **Jetson Orin Nano *Super* Dev Kit** (same ~$249 price) | ~2.5× the AI throughput (67 vs ~40 TOPS) for the same money after the Dec-2024 firmware/SKU refresh. |
| Accelerator | Add Google Coral USB TPU | **Drop the Coral** | Redundant with the Jetson GPU and fights the PyTorch/TensorRT stack (Coral only runs int8 TFLite). It adds cost and complexity for no gain here. |
| Plate camera | "Optional telephoto" | **Global-shutter USB3 camera + fixed telephoto lens** | Rolling-shutter cameras smear fast-moving plates into unreadable garbage. Global shutter is the single biggest ALPR quality lever. |
| OS storage | Boot + record from microSD | **Boot/OS on NVMe SSD; record to high-endurance card + USB SSD** | Continuous video writes destroy consumer SD cards in weeks. |
| Power | 12V→5V buck converter | **Automotive DC-DC with ignition sense + supercap for graceful shutdown** | Cars have dirty power, load dumps, and no clean shutdown. Naive power kills the SD card's filesystem and drains the battery. |
| Speed/pose | GPS + separate IMU | **OBD-II for true ego speed + GNSS dead-reckoning module** | OBD wheel speed is far more reliable than GPS-derived speed; fused GNSS+IMU survives tunnels/urban canyons. |
| Software | Hand-rolled tracking | **Ultralytics YOLO with built-in ByteTrack/BoT-SORT + TensorRT export** | Don't reinvent tracking; get 2–4× inference speedup by exporting to TensorRT. |
| Scope | Detect everything at once | **Tiered rollout by detection difficulty** | Ego-vehicle events (lane departure, collision, tailgating) are ~10× easier and more reliable than judging a cross-traffic vehicle's red-light run from a moving platform. Ship the reliable subset first. |

---

## Repository layout

```
traffic-violation-detector/
├── README.md                      ← you are here
├── docs/                          ← the full plan and buildable designs
│   ├── 01-project-plan.md         ← phases, milestones, effort, budget
│   ├── 02-architecture.md         ← system + software architecture, data flow
│   ├── 03-hardware-bom.md         ← full bill of materials, wiring, power, mounting
│   ├── 04-software-stack.md       ← OS, libraries, models, versions, setup
│   ├── 05-detection-design.md     ← how each violation is detected + difficulty tiers
│   ├── 06-legal-and-privacy.md    ← legal reality, privacy controls, retention
│   └── 07-changes-from-original-spec.md
├── src/tvd/                       ← the buildable program (Python package)
│   ├── pipeline.py                ← threaded capture→detect→track→rules→record
│   ├── capture.py                 ← camera capture (GStreamer/OpenCV)
│   ├── detector.py                ← YOLO wrapper (TensorRT-ready)
│   ├── recorder.py                ← pre/post-event ring-buffer clip recorder
│   ├── storage.py                 ← SQLite evidence/metadata store
│   ├── alpr.py                    ← optional plate detection + OCR
│   ├── light_classifier.py        ← traffic-light red/yellow/green classifier
│   ├── review.py                  ← local web UI to browse recorded events
│   ├── geometry.py                ← calibration, distance & speed helpers
│   ├── sensors/                   ← gps.py, imu.py, obd.py (graceful fallbacks)
│   └── violations/                ← rule engine + per-violation detectors
├── config/config.yaml             ← all tunable parameters in one place
├── docker/Dockerfile.jetson       ← reproducible build for Jetson (L4T base)
├── deploy/tvds.service            ← systemd unit for auto-start on boot
├── scripts/setup_jetson.sh        ← one-shot device provisioning
└── tests/                         ← unit tests for the pure-logic rule engine
```

## Quick start (development machine, no hardware needed)

The pipeline degrades gracefully: with no cameras/sensors it runs off a video
file and simulated sensors so you can develop the logic on a laptop.

```bash
cd traffic-violation-detector
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run the rule-engine unit tests (pure logic, no hardware, no models):
pytest -q

# Run the pipeline against a sample video with the sim sensor backend:
python -m tvd.main --source sample.mp4 --config config/config.yaml --sim-sensors

# Browse recorded events in the local review UI (http://127.0.0.1:8080):
python -m tvd.review --db data/events.db
```

## Getting started on the real device

1. Read [`docs/03-hardware-bom.md`](docs/03-hardware-bom.md) and order parts.
2. Flash and provision: [`docs/04-software-stack.md`](docs/04-software-stack.md) →
   `scripts/setup_jetson.sh`.
3. Calibrate cameras: [`docs/05-detection-design.md`](docs/05-detection-design.md#calibration).
4. `sudo systemctl enable --now tvds` (see `deploy/tvds.service`).

## Status

This repository contains the **design and a runnable software scaffold**. The
architecture, interfaces, config, and rule engine are complete and testable. The
per-violation detectors ship with working implementations for all **Tier-1**
events plus **Tier-2 stop-sign compliance** and the **Tier-2 red-light entry**
rule; the remaining Tier-3 advisory detectors and the perception front-ends they
depend on (light-state classifier, ALPR OCR) are clearly marked stubs. CI runs
the 25-test suite on Python 3.10–3.12 on every push. See
[`docs/01-project-plan.md`](docs/01-project-plan.md) for what is done vs. planned.
