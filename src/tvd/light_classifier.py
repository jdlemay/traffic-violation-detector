"""Traffic-light state classification from a detected `traffic light` crop.

This is the perception front-end for the Tier-2 red-light rule (see
violations/red_light.py): YOLO localizes the light; this module answers
"what color is it showing?".

Approach: a deliberately simple, fast color-dominance classifier in RGB space —
find bright, saturated pixels and score them as red / yellow / green by channel
ratios, then pick the dominant class. Pure numpy (no cv2 dependency), so it is
unit-testable everywhere and cheap enough to run per frame on every light crop.

Known limits (by design, see docs/05): sun glare and washed-out LEDs degrade
it. If field precision is insufficient, swap this for a small trained CNN — the
`classify_light_color` signature is the stable interface.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np

# Minimum fraction of the crop that must vote for a color to trust the result.
MIN_VOTE_FRAC = 0.02
# A lit lamp is bright: ignore pixels below this max-channel value (0-255).
MIN_BRIGHTNESS = 90
# And saturated: max-min channel spread must exceed this.
MIN_SPREAD = 40


def classify_light_color(crop_bgr: np.ndarray) -> Tuple[str, float]:
    """Classify a traffic-light crop as ('red'|'yellow'|'green'|'unknown', conf).

    `crop_bgr` is an HxWx3 uint8 image in BGR channel order (OpenCV convention).
    Confidence is the winning color's share of bright-saturated pixels, capped
    at 1.0; ('unknown', 0.0) when too few pixels qualify.
    """
    if crop_bgr is None or crop_bgr.ndim != 3 or crop_bgr.shape[2] != 3 \
            or crop_bgr.size == 0:
        return "unknown", 0.0

    px = crop_bgr.reshape(-1, 3).astype(np.int16)
    b, g, r = px[:, 0], px[:, 1], px[:, 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)

    lit = (mx >= MIN_BRIGHTNESS) & ((mx - mn) >= MIN_SPREAD)
    n_lit = int(lit.sum())
    total = px.shape[0]
    if n_lit < max(4, MIN_VOTE_FRAC * total):
        return "unknown", 0.0

    r, g, b = r[lit], g[lit], b[lit]
    # Red: red dominant over green and blue.
    red_votes = (r > g * 1.5) & (r > b * 1.5)
    # Green: green dominant over red and blue (LED greens skew cyan; allow b).
    green_votes = (g > r * 1.3) & (g > b * 0.9)
    # Yellow/amber: red and green both high and comparable, blue low.
    yellow_votes = (r > b * 1.5) & (g > b * 1.5) & \
                   (np.abs(r - g) < 0.45 * np.maximum(r, g)) & ~red_votes

    counts = {
        "red": int(red_votes.sum()),
        "yellow": int(yellow_votes.sum()),
        "green": int(green_votes.sum()),
    }
    color = max(counts, key=counts.get)
    votes = counts[color]
    if votes < max(4, MIN_VOTE_FRAC * total):
        return "unknown", 0.0
    conf = min(1.0, votes / n_lit)
    return color, float(conf)
