"""Unit tests for the traffic-light color classifier (pure numpy)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tvd.light_classifier import classify_light_color


def crop_with_lamp(bgr, size=32, radius=8):
    """A dark traffic-light housing with one lit circular lamp."""
    img = np.full((size * 3, size, 3), 20, dtype=np.uint8)  # dark housing
    cy, cx = size // 2, size // 2
    yy, xx = np.ogrid[:size * 3, :size]
    mask = (yy - cy) ** 2 + (xx - cx) ** 2 <= radius ** 2
    img[mask] = bgr
    return img


def test_red_lamp():
    color, conf = classify_light_color(crop_with_lamp((30, 30, 230)))
    assert color == "red" and conf > 0.5


def test_green_lamp():
    color, conf = classify_light_color(crop_with_lamp((90, 220, 40)))
    assert color == "green" and conf > 0.5


def test_yellow_lamp():
    color, conf = classify_light_color(crop_with_lamp((30, 200, 230)))
    assert color == "yellow" and conf > 0.5


def test_dark_crop_unknown():
    img = np.full((96, 32, 3), 15, dtype=np.uint8)  # unlit housing
    color, conf = classify_light_color(img)
    assert color == "unknown" and conf == 0.0


def test_grey_daylight_unknown():
    # Bright but unsaturated (washed-out/grey) crop must not vote a color.
    img = np.full((96, 32, 3), 180, dtype=np.uint8)
    color, _ = classify_light_color(img)
    assert color == "unknown"


def test_garbage_input_unknown():
    assert classify_light_color(None) == ("unknown", 0.0)
    assert classify_light_color(np.zeros((0, 0, 3), dtype=np.uint8)) == ("unknown", 0.0)
    assert classify_light_color(np.zeros((5, 5), dtype=np.uint8)) == ("unknown", 0.0)
