# 04 · Software Stack & Setup

## 1. Stack overview

| Layer | Choice | Why |
| --- | --- | --- |
| OS | **NVIDIA JetPack 6.x** (Ubuntu 22.04 + L4T) | Vendor stack; ships CUDA, cuDNN, TensorRT, HW codec. |
| Boot | **NVMe** | Speed + endurance; SD boot is fragile under continuous write. |
| Containerization | **Docker** with `nvidia-container-runtime` | Reproducible builds; base off `nvcr.io/nvidia/l4t-*`. |
| Language | **Python 3.10** | Ecosystem; hot paths already native (CUDA/TensorRT/GStreamer). |
| Video I/O | **GStreamer** (HW `nvv4l2` elements) + OpenCV | HW-accelerated decode/encode; avoid CPU x264 for continuous record. |
| Detection | **Ultralytics YOLO11** (n/s) → **TensorRT FP16** | SOTA-ish, easy training, built-in tracking, fast on Jetson after TRT export. |
| Tracking | **ByteTrack / BoT-SORT** (built into Ultralytics) | Don't hand-roll tracking. |
| Lanes | Classic CV (Hough/poly-fit) first, optional **CLRNet/LaneNet** later | Start simple; upgrade if needed. |
| Signs/signals | Fine-tuned YOLO on traffic-sign/light classes (e.g. Mapillary, LISA, DFG) | Custom classes beyond COCO. |
| ALPR | **Plate detector (YOLO) + OCR** (`fast-plate-ocr` / PaddleOCR / open ALPR) | Two-stage; global-shutter camera does the heavy lifting. |
| Sensors | `gpsd`/`pynmea2`, `smbus2` (IMU), `python-OBD` | Standard libs. |
| Storage | **SQLite** (metadata) + files on USB SSD | Local-first; PostgreSQL only if/when a server/fleet exists. |
| Video mux | **FFmpeg** + GStreamer segment muxer | Segmenting, clip assembly, hashing. |
| Service mgmt | **systemd** | Auto-start, restart, clean shutdown. |
| Review UI | Small local web app (FastAPI + static) — Phase 7 | Browse/scrub/export events. |

## 2. `requirements.txt` (dev + device)

See [`../requirements.txt`](../requirements.txt). On the Jetson, install
PyTorch/torchvision from the **NVIDIA Jetson wheels index** (not PyPI) so they
match CUDA/JetPack; on a dev laptop, plain PyPI is fine. TensorRT ships with
JetPack — do not `pip install` it on device.

## 3. Device provisioning

Automated in [`../scripts/setup_jetson.sh`](../scripts/setup_jetson.sh). Summary:

```bash
# 1. Flash JetPack 6.x via SDK Manager or the Jetson installer, boot from NVMe.
# 2. Basic tooling
sudo apt-get update && sudo apt-get install -y \
    python3-pip python3-venv git ffmpeg gpsd gpsd-clients i2c-tools \
    gstreamer1.0-tools gstreamer1.0-plugins-{base,good,bad}
# 3. Enable I2C, add user to groups
sudo usermod -aG i2c,dialout,video $USER
# 4. Python env + deps (Jetson torch wheels from NVIDIA index)
python3 -m venv ~/tvds-venv && source ~/tvds-venv/bin/activate
pip install -r requirements.txt
# 5. Export the YOLO model to TensorRT (one-time, on-device):
yolo export model=yolo11s.pt format=engine half=True device=0
# 6. Install the service
sudo cp deploy/tvds.service /etc/systemd/system/ && \
    sudo systemctl daemon-reload && sudo systemctl enable --now tvds
```

## 4. Model strategy

1. **Start with COCO-pretrained YOLO11** — it already detects car, truck, bus,
   motorcycle, bicycle, person, traffic light, stop sign. That covers Tier-1 and
   a chunk of Tier-2 with zero training.
2. **Fine-tune for signs/signals** on public datasets (Mapillary Traffic Sign,
   LISA, DFG, Bosch Small Traffic Lights) when you reach Phase 6.
3. **Export to TensorRT FP16** on the device for 2–4× speedup. INT8 is possible
   with a calibration set for another jump, but validate accuracy carefully.
4. **Version and hash models**; record `model_id` in each event's `meta_json` so
   detections are reproducible/auditable.

## 5. Why not DeepStream (yet)?

NVIDIA DeepStream is the most efficient path (fully HW pipeline, multi-stream) and
is the right destination for a production/fleet build. It has a steep learning
curve and is harder to iterate on. Plan: **build and validate logic in the Python
pipeline first, then port the capture→detect→track hot path to DeepStream in a
later phase** if you need more streams or lower power. The module boundaries in
this repo (capture/detector/tracker are isolated) make that port straightforward.

## 6. Reproducibility

- Everything runs in Docker off an L4T base image
  ([`../docker/Dockerfile.jetson`](../docker/Dockerfile.jetson)).
- All tunables live in [`../config/config.yaml`](../config/config.yaml).
- Pin model versions; keep the TensorRT engine build reproducible per device
  (engines are device/JetPack-specific — rebuild on each device, don't copy).
