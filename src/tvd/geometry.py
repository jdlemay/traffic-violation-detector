"""Camera geometry: calibration, pixel->ground, distance & speed helpers.

Two estimators:
  * homography-based (accurate, needs one-time calibration), and
  * a pinhole flat-road fallback (rough, needs only camera height + intrinsics).

All pure numpy; testable without hardware. See docs/05 for the calibration
procedure.
"""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np


def fit_ground_homography(
    image_points: Sequence[Sequence[float]],
    ground_points: Sequence[Sequence[float]],
) -> np.ndarray:
    """Least-squares homography H mapping image (u,v,1) -> ground (X,Y,1).

    Provide >= 4 correspondences: image pixels of known ground locations and
    their real-world ground coordinates in meters (X right, Y forward). Returns
    a 3x3 matrix. Uses the standard DLT formulation.
    """
    img = np.asarray(image_points, dtype=float)
    gnd = np.asarray(ground_points, dtype=float)
    if img.shape[0] < 4 or img.shape != gnd.shape:
        raise ValueError("need >= 4 matching image/ground point pairs")

    A = []
    for (u, v), (X, Y) in zip(img, gnd):
        A.append([u, v, 1, 0, 0, 0, -X * u, -X * v, -X])
        A.append([0, 0, 0, u, v, 1, -Y * u, -Y * v, -Y])
    _, _, Vt = np.linalg.svd(np.asarray(A))
    H = Vt[-1].reshape(3, 3)
    return H / H[2, 2]


def image_to_ground(H: np.ndarray, u: float, v: float) -> tuple[float, float]:
    """Map an image point (u,v) on the road plane to ground meters (X, Y)."""
    p = H @ np.array([u, v, 1.0])
    return float(p[0] / p[2]), float(p[1] / p[2])


def distance_to_bbox_ground(
    H: Optional[np.ndarray],
    bbox: Sequence[float],
    *,
    camera_height_m: float = 1.3,
    focal_px: Optional[float] = None,
    image_height: Optional[int] = None,
) -> Optional[float]:
    """Estimate longitudinal distance (m) to a vehicle from its bbox.

    Uses the ground-contact point (bottom-center of the box). If a homography is
    available it is used; otherwise a pinhole flat-road fallback is used when
    focal length + image height are known. Returns None if underdetermined.
    """
    x1, y1, x2, y2 = bbox
    u = 0.5 * (x1 + x2)
    v = y2  # bottom edge = where the vehicle meets the road

    if H is not None:
        X, Y = image_to_ground(H, u, v)
        return float(np.hypot(X, Y))

    # Pinhole flat-road fallback: distance = f * H_cam / (v - v_horizon).
    if focal_px and image_height:
        v_horizon = image_height / 2.0  # assumes level camera; refine w/ IMU pitch
        dv = v - v_horizon
        if dv <= 1e-3:
            return None
        return float(focal_px * camera_height_m / dv)
    return None


def time_gap_seconds(distance_m: float, ego_speed_mps: float) -> Optional[float]:
    """Following time gap = distance / speed. None if stopped."""
    if ego_speed_mps <= 1e-3:
        return None
    return distance_m / ego_speed_mps


def time_to_collision(distance_m: float, closing_speed_mps: float) -> Optional[float]:
    """TTC = distance / closing speed. None if not closing."""
    if closing_speed_mps <= 1e-3:
        return None
    return distance_m / closing_speed_mps
