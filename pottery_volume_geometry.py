"""Small geometry helpers shared by the GUI and analysis modules."""

from __future__ import annotations

import math


def pixel_distance(point_a: tuple[float, float], point_b: tuple[float, float]) -> float:
    """Return the distance between two image points in pixels."""
    distance = math.hypot(point_b[0] - point_a[0], point_b[1] - point_a[1])
    if not math.isfinite(distance):
        raise ValueError("2点間の距離を計算できません。")
    return distance
