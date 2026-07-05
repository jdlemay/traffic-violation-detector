#!/usr/bin/env bash
# One-shot provisioning for a Jetson Orin Nano (Super) running JetPack 6.x.
# Assumes JetPack is already flashed and the device boots from NVMe.
set -euo pipefail

echo "==> System packages"
sudo apt-get update
sudo apt-get install -y \
    python3-pip python3-venv git ffmpeg \
    gpsd gpsd-clients i2c-tools \
    gstreamer1.0-tools gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
    python3-opencv

echo "==> Groups (I2C, serial, video)"
sudo usermod -aG i2c,dialout,video "$USER"

echo "==> Python environment"
python3 -m venv ~/tvds-venv
# shellcheck disable=SC1090
source ~/tvds-venv/bin/activate
pip install --upgrade pip
# NOTE: on Jetson install torch/torchvision from the NVIDIA Jetson wheel index
# to match CUDA/JetPack, THEN the rest. TensorRT is already provided by JetPack.
pip install pyyaml numpy pynmea2 smbus2 obd ultralytics

echo "==> Export YOLO to TensorRT (one-time, device-specific)"
# Rebuild the engine on THIS device; engines are not portable across devices.
yolo export model=yolo11s.pt format=engine half=True device=0 || \
    echo "   (export skipped — run manually once weights are present)"

echo "==> Verify capture devices"
v4l2-ctl --list-devices || true

cat <<'EOF'

Next steps:
  1. Wire power (DC-DC + ignition sense + supercap) — see docs/03.
  2. Calibrate the camera homography — see docs/05 (Calibration).
  3. Edit config/config.yaml (sources, thresholds, privacy).
  4. Install the service:
       sudo cp deploy/tvds.service /etc/systemd/system/
       sudo systemctl daemon-reload && sudo systemctl enable --now tvds
  5. Watch logs: journalctl -u tvds -f
EOF
echo "==> Done. Log out/in for group changes to take effect."
