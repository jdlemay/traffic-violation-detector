"""Unit tests for geometry helpers (homography, distance, time-gap, TTC)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tvd import geometry


def test_homography_roundtrip_identity_like():
    # Map four image points to known ground points; recovered mapping should
    # reproduce the ground points from the image points.
    img = [(100, 700), (1180, 700), (100, 400), (1180, 400)]
    gnd = [(-2.0, 5.0), (2.0, 5.0), (-4.0, 20.0), (4.0, 20.0)]
    H = geometry.fit_ground_homography(img, gnd)
    for (u, v), (X, Y) in zip(img, gnd):
        x, y = geometry.image_to_ground(H, u, v)
        assert abs(x - X) < 1e-6
        assert abs(y - Y) < 1e-6


def test_homography_requires_four_points():
    try:
        geometry.fit_ground_homography([(0, 0), (1, 1)], [(0, 0), (1, 1)])
    except ValueError:
        return
    raise AssertionError("expected ValueError for < 4 points")


def test_pinhole_distance_fallback_monotonic():
    # Lower bbox bottom (closer to horizon) => farther away.
    near = geometry.distance_to_bbox_ground(
        None, (600, 400, 700, 690), focal_px=1000, image_height=720)
    far = geometry.distance_to_bbox_ground(
        None, (600, 380, 700, 400), focal_px=1000, image_height=720)
    assert near is not None and far is not None
    assert far > near


def test_time_gap_and_ttc():
    assert abs(geometry.time_gap_seconds(30.0, 15.0) - 2.0) < 1e-9
    assert geometry.time_gap_seconds(30.0, 0.0) is None
    assert abs(geometry.time_to_collision(20.0, 10.0) - 2.0) < 1e-9
    assert geometry.time_to_collision(20.0, -5.0) is None  # not closing
