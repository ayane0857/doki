"""Integrate radial profiles and cross-check volume with section geometry."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, NotRequired, TypedDict

import numpy as np

from doki.analysis.profiles import Profiles

if TYPE_CHECKING:
    from shapely.geometry import Polygon


class VolumeResult(TypedDict):
    """Core numeric results emitted by the volume integration.

    Note on volumetric units:
        When a millimetre scale is provided (``mm_per_px is not None``),
        both ``_cm3`` and ``_ml`` fields are emitted for reporting and TSV convenience.
        Since 1 cm³ equals 1 mL, ``capacity_cm3`` and ``capacity_ml`` (and their
        wall volume counterparts) are mathematically equivalent.
    """

    units: dict[str, str]
    vessel_height: float
    mouth_diameter: float
    maximum_diameter: float
    liquid_level_y_px: float
    capacity: float
    wall_volume: float
    pappus_wall_volume: float
    pappus_difference_percent: float
    section_area: float
    section_centroid_radius: float
    mm_per_px: float | None
    capacity_cm3: NotRequired[float]
    capacity_ml: NotRequired[float]
    wall_volume_cm3: NotRequired[float]
    wall_volume_ml: NotRequired[float]
    pappus_wall_volume_cm3: NotRequired[float]
    pappus_wall_volume_ml: NotRequired[float]


def profile_section_polygon(
    profiles: Profiles,
    axis_x: float,
) -> Polygon:
    """Build and validate the right-side vessel wall polygon from radial profiles."""
    if len(profiles.y_px) < 2:
        raise ValueError("断面輪郭をPolygonにするには2行以上必要です。")
    if not np.all(np.isfinite(profiles.r_in_px)) or not np.all(
        np.isfinite(profiles.r_out_px)
    ):
        raise ValueError("断面輪郭に無効な半径があります。")
    if len(profiles.r_in_px) != len(profiles.y_px) or len(profiles.r_out_px) != len(
        profiles.y_px
    ):
        raise ValueError("断面輪郭の行数が一致しません。")

    inner = [
        (axis_x + float(radius), float(y))
        for y, radius in zip(profiles.y_px, profiles.r_in_px, strict=False)
    ]
    outer = [
        (axis_x + float(radius), float(y))
        for y, radius in zip(profiles.y_px, profiles.r_out_px, strict=False)
    ]
    from shapely import geometry
    from shapely.validation import explain_validity

    polygon = geometry.Polygon(inner + list(reversed(outer)))
    if polygon.is_empty or polygon.area <= 0:
        raise ValueError("断面Polygonの面積がありません。")
    if not polygon.is_valid:
        raise ValueError(f"断面Polygonが無効です: {explain_validity(polygon)}")
    return polygon


def _profile_at(y_px: np.ndarray, values: np.ndarray, y: float) -> float:
    """Linearly interpolate a radial profile at a requested image row."""
    return float(np.interp(y, y_px, values))


def compute_volumes(
    profiles: Profiles,
    section_mask: np.ndarray,
    axis_x: float,
    mm_per_px: float | None = None,
    section_mode: str = "filled",
) -> VolumeResult:
    """Integrate capacity and wall volume; cross-check wall volume using Pappus."""
    y = profiles.y_px
    rin = profiles.r_in_px
    rout = profiles.r_out_px
    level = profiles.liquid_y_px
    start_index = int(np.searchsorted(y, level, side="left"))
    y_fill = y[start_index:]
    rin_fill = rin[start_index:]
    if len(y_fill) == 0:
        capacity_px3 = 0.0
    else:
        if y_fill[0] > level:
            y_fill = np.r_[level, y_fill]
            rin_fill = np.r_[_profile_at(y, rin, level), rin_fill]
        capacity_px3 = math.pi * float(np.trapezoid(rin_fill**2, y_fill))
    wall_px3 = math.pi * float(np.trapezoid(rout**2 - rin**2, y))

    section_polygon = profile_section_polygon(profiles, axis_x)
    area_px2 = float(section_polygon.area)
    centroid_x_px = float(section_polygon.centroid.x)
    centroid_radius_px = centroid_x_px - axis_x
    pappus_px3 = 2.0 * math.pi * centroid_radius_px * area_px2
    diff_pct = abs(pappus_px3 - wall_px3) / wall_px3 * 100 if wall_px3 else 0.0
    px_scale = mm_per_px if mm_per_px is not None else 1.0
    unit = "mm" if mm_per_px is not None else "px"
    volume_unit = "mm3" if mm_per_px is not None else "px3"
    volume_scale = px_scale**3
    length_scale = px_scale
    mouth_diameter = 2.0 * float(rin[0]) * length_scale
    max_diameter = 2.0 * float(np.max(rout)) * length_scale
    height = (profiles.bottom_y_px - profiles.top_y_px) * length_scale
    result: VolumeResult = {
        "units": {"length": unit, "volume": volume_unit},
        "vessel_height": height,
        "mouth_diameter": mouth_diameter,
        "maximum_diameter": max_diameter,
        "liquid_level_y_px": level,
        "capacity": capacity_px3 * volume_scale,
        "wall_volume": wall_px3 * volume_scale,
        "pappus_wall_volume": pappus_px3 * volume_scale,
        "pappus_difference_percent": diff_pct,
        "section_area": area_px2 * px_scale**2,
        "section_centroid_radius": centroid_radius_px * length_scale,
        "mm_per_px": mm_per_px,
    }
    if mm_per_px is not None:
        volume_ml = capacity_px3 * volume_scale / 1000.0
        wall_ml = wall_px3 * volume_scale / 1000.0
        pappus_ml = pappus_px3 * volume_scale / 1000.0
        result.update(
            {
                "capacity_cm3": volume_ml,
                "capacity_ml": volume_ml,
                "wall_volume_cm3": wall_ml,
                "wall_volume_ml": wall_ml,
                "pappus_wall_volume_cm3": pappus_ml,
                "pappus_wall_volume_ml": pappus_ml,
            }
        )
    return result
