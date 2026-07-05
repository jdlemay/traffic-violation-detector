# 07 · Changes from the Original Spec (and why)

The original Master Specification is sound in intent. These are the deliberate
engineering changes I made for reliability, cost-efficiency, and buildability,
with the reasoning so you can accept or reject each on its merits.

## Hardware

### 1. Jetson Orin Nano → Jetson Orin Nano **Super** (same price)
In Dec 2024 NVIDIA released a firmware/SKU update that roughly **doubles** the
Orin Nano's AI throughput (to ~67 TOPS) at the **same ~$249** price and rebadged
the dev kit as "Super." There is no reason to buy the older SKU. More headroom
means you can run a larger YOLO model or hold frame rate more easily.

### 2. Drop the Google Coral USB TPU
The spec lists the Coral as optional. On a Jetson it's **counterproductive**:
- The Jetson GPU + TensorRT already accelerates inference far better than a Coral.
- Coral only runs **int8 TFLite** models, which fights the PyTorch/Ultralytics/
  TensorRT toolchain the rest of the stack uses — you'd maintain a second,
  awkward model path for no throughput gain.
- It's extra cost, USB bandwidth, heat, and a failure point.
Use it only if your compute were a Raspberry Pi (no GPU). Here: remove it.

### 3. Plate camera must be **global shutter**
The spec says "optional telephoto camera for license plates." The bigger issue
than focal length is **shutter type**. Rolling-shutter sensors smear fast-moving
plates into unreadable characters. A **global-shutter** sensor freezes the frame.
This single choice is the difference between ALPR that works and ALPR that
doesn't. Pair it with a fixed telephoto lens for pixels-on-plate.

### 4. Boot from NVMe; record to high-endurance media
The spec boots and records from a microSD. Continuous video writing **destroys
consumer SD cards** (they're not rated for sustained writes) and SD boot is slow
and fragile. Recommendation: **OS on NVMe**, ring buffer on a **dashcam-rated
high-endurance card**, archive on a **USB SSD**. This is the difference between a
device that runs for years and one that corrupts its filesystem in weeks.

### 5. Real automotive power, not a bare buck converter
The spec lists a "12V→5V buck converter." Vehicle power is hostile: cranking
dips, alternator **load dumps to 40V+**, and no clean shutdown. Add:
- An **automotive-grade DC-DC** with load-dump/transient protection.
- **Ignition sense** (switched-12V line) so the device knows the engine is off.
- A **supercapacitor** reserve so software can `shutdown -h` cleanly on power
  loss — protecting the filesystem and the last clip.
Skipping this is the #1 cause of dead dashcam builds.

### 6. Fused GNSS+dead-reckoning and OBD-II speed
The spec lists GPS + IMU + optional OBD. Promote OBD to **primary ego-speed
source** (wheel speed is more accurate and lower-latency than GPS-derived speed)
and use a **GNSS module with dead reckoning** (e.g. u-blox ZED-F9R) so position/
speed survive tunnels and urban canyons. Fuse with the IMU. Accurate ego speed is
the backbone of tailgating, TTC, and any other-vehicle speed estimate.

## Software

### 7. Don't hand-roll tracking — use Ultralytics' built-in ByteTrack/BoT-SORT
The spec's pipeline says "track vehicles." Ultralytics YOLO already integrates
ByteTrack and BoT-SORT with one call. Use them; don't write a tracker.

### 8. Export models to **TensorRT FP16**
Running raw PyTorch on the Jetson leaves 2–4× performance on the table. Export
YOLO to a TensorRT engine on-device. This is often the difference between 12 fps
and 30+ fps.

### 9. Ring-buffer/segment recording for guaranteed pre-roll
The spec says "save event clip before and after incident" but not how. The robust
pattern is a **continuous segment ring buffer**: always encode short segments via
the HW encoder; on an event, concatenate the last N seconds already on disk plus
the next M seconds. This guarantees pre-roll without CPU-expensive re-encoding and
without a giant in-RAM buffer.

### 10. Tiered rollout by detection difficulty
The spec lists nine detections as a flat goal set. In practice their difficulty
spans an order of magnitude. Judging a **cross-traffic vehicle's** red-light run
from a moving camera is a research-grade problem; detecting **your own** hard
braking or lane departure is straightforward and immediately valuable. The plan
sequences **Tier-1 ego events first**, then scene understanding, then advisory
other-vehicle detection — so you ship reliable value early instead of chasing the
hardest cases up front. See [`01-project-plan.md`](01-project-plan.md#3-difficulty-tiers-drives-the-rollout-order).

### 11. Privacy-protective defaults
Added explicit privacy controls (video-only default, event-scoped ALPR, retention
purge, at-rest encryption hooks, integrity hashing) — not in the original spec but
essential given the device records the public and reads plates. See
[`06-legal-and-privacy.md`](06-legal-and-privacy.md).

### 12. Honest scope: recorder/analytics, not enforcement
Reframed the product from an implied "catch violators" tool to a **smart incident
recorder + driver-safety analytics** device, because a private camera can't issue
citations and the enforcement framing creates legal risk and over-promises on the
hardest detections. Same hardware, same detections — but positioned where it's
reliable and defensible.

## Kept from the original spec
Jetson-class edge compute, wide forward camera, GPS + IMU + OBD sensor set, Docker
+ Python + OpenCV + PyTorch + Ultralytics YOLO + OCR + SQLite/PostgreSQL + FFmpeg,
the capture→detect→track→identify→record pipeline shape, the evidence fields
(clip, stills, timestamp, GPS, speed, type, confidence), and the phased build
approach. The bones were right; these changes harden them.
