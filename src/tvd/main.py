"""CLI entrypoint.

Examples:
  # Laptop dev: no hardware, simulated sensors + camera, 60 frames:
  python -m tvd.main --sim --frames 60

  # Run against a recorded drive with simulated sensors:
  python -m tvd.main --source drive.mp4 --sim-sensors

  # On the Jetson (real hardware, default config):
  python -m tvd.main --config config/config.yaml
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from the repo without installing (src/ layout).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tvd.config import Config          # noqa: E402
from tvd.pipeline import Pipeline      # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description="Traffic Violation Detection System")
    p.add_argument("--config", default="config/config.yaml")
    p.add_argument("--source", default=None,
                   help="camera index, device path, GStreamer pipeline, or video file")
    p.add_argument("--sim", action="store_true",
                   help="simulate BOTH camera and sensors (pure logic run)")
    p.add_argument("--sim-sensors", action="store_true",
                   help="simulate sensors only (use a real --source video/camera)")
    p.add_argument("--frames", type=int, default=None, help="stop after N frames")
    args = p.parse_args(argv)

    cfg_path = Path(args.config)
    cfg = Config.load(cfg_path) if cfg_path.exists() else Config({})

    pipe = Pipeline(
        cfg,
        source=args.source,
        sim_sensors=args.sim or args.sim_sensors,
        sim_camera=args.sim,
        max_frames=args.frames,
    )
    pipe.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
