"""Extract and edit radial wall profiles from detected sections."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from doki.analysis.image import SectionResult


@dataclass
class Profiles:
    """Radial inner and outer wall profiles indexed by image row."""

    y_px: np.ndarray
    r_in_px: np.ndarray
    r_out_px: np.ndarray
    top_y_px: float
    bottom_y_px: float
    liquid_y_px: float
    warnings: list[str] = field(default_factory=list)


def apply_profile_overrides(
    profiles: Profiles,
    inner_radius_px: np.ndarray | None = None,
    outer_radius_px: np.ndarray | None = None,
    warnings: list[str] | None = None,
) -> Profiles:
    """Create a profiles copy with manually corrected inner/outer radii."""
    r_in = profiles.r_in_px.copy()
    r_out = profiles.r_out_px.copy()
    if inner_radius_px is not None:
        if inner_radius_px.shape != r_in.shape:
            raise ValueError("修正した内面輪郭の行数が自動輪郭と一致しません。")
        r_in = np.asarray(inner_radius_px, dtype=float).copy()
    if outer_radius_px is not None:
        if outer_radius_px.shape != r_out.shape:
            raise ValueError("修正した外面輪郭の行数が自動輪郭と一致しません。")
        r_out = np.asarray(outer_radius_px, dtype=float).copy()
    if not np.all(np.isfinite(r_in)) or not np.all(np.isfinite(r_out)):
        raise ValueError("輪郭の修正値に無効な数値があります。")
    r_in = np.maximum(r_in, 0.0)
    r_out = np.maximum(r_out, r_in + 0.25)
    profile_warnings = list(profiles.warnings)
    if warnings:
        profile_warnings.extend(warnings)
    return Profiles(
        profiles.y_px.copy(),
        r_in,
        r_out,
        profiles.top_y_px,
        profiles.bottom_y_px,
        profiles.liquid_y_px,
        profile_warnings,
    )


def _smooth(values: np.ndarray, window: int) -> np.ndarray:
    """Apply a short Savitzky-Golay smoother when enough samples exist."""
    if window <= 2 or len(values) < 5:
        return values
    win = min(
        window if window % 2 else window - 1,
        len(values) if len(values) % 2 else len(values) - 1,
    )
    if win < 5:
        return values

    from scipy.signal import savgol_filter

    return np.asarray(
        savgol_filter(
            values, window_length=win, polyorder=min(2, win - 1), mode="interp"
        ),
        dtype=float,
    )


def extract_profiles(
    section: SectionResult,
    axis_x: float,
    liquid_level_y: float | None = None,
    smooth_window: int = 5,
) -> Profiles:
    """Read inner/outer radial extents for each row and interpolate short gaps."""
    mask = section.mask > 0
    y_all = np.flatnonzero(np.any(mask, axis=1))
    if len(y_all) < 2:
        raise ValueError(
            "器壁輪郭の行数が足りません。検出条件または --crop を調整してください。"
        )

    # Ignore isolated row fragments outside the main vertical run.
    breaks = np.flatnonzero(np.diff(y_all) > max(3, int(mask.shape[0] * 0.03)))
    segments = np.split(y_all, breaks + 1)
    ys = max(segments, key=len)
    top, bottom = int(ys[0]), int(ys[-1])
    if section.mode == "filled":
        # The flood-filled interior omits its one-pixel contour stroke. Extend the
        # detected vertical limits to the closed outline itself.
        top = max(0, top - 1)
        bottom = min(mask.shape[0] - 1, bottom + 1)
    y_px = np.arange(top, bottom + 1, dtype=float)
    raw_in = np.full(len(y_px), np.nan, dtype=float)
    raw_out = np.full(len(y_px), np.nan, dtype=float)
    for index, y in enumerate(range(top, bottom + 1)):
        xs = np.flatnonzero(mask[y] & (np.arange(mask.shape[1]) > axis_x))
        if len(xs) < 1:
            continue
        # Pixel cells extend half a pixel beyond their center coordinates.
        if section.mode == "filled":
            # Flood fill excludes the black outline pixels; put their centerlines
            # back so thin walls are not systematically underestimated.
            raw_in[index] = max(0.0, float(xs[0]) - axis_x - 1.0)
            raw_out[index] = max(raw_in[index] + 0.5, float(xs[-1]) - axis_x + 1.0)
        else:
            raw_in[index] = max(0.0, float(xs[0]) - axis_x)
            raw_out[index] = max(raw_in[index] + 0.5, float(xs[-1]) - axis_x)
    if section.mode == "lines":
        # A long top measurement/rim stroke can run from the axis into the mouth.
        # It is not the inner wall. Reject only near-axis outliers near the mouth.
        head = max(5, int(len(y_px) * 0.15))
        outliers = [
            idx
            for idx in range(min(head, len(y_px)))
            if np.isfinite(raw_in[idx])
            and np.isfinite(raw_out[idx])
            and raw_out[idx] > (section.roi[2] - section.roi[0]) * 0.30
            and raw_in[idx] < raw_out[idx] * 0.15
        ]
        if outliers:
            raw_in[outliers] = np.nan
            section.warnings.append(
                "口縁付近の軸から伸びる横線を内面輪郭から除外しました。"
            )
        if len(y_px) >= 4:
            # A terminal fragment can survive filtering; reject a jump unlike recent contour movement.
            terminal_adjusted = False
            for profile in (raw_in, raw_out):
                recent = profile[-4:-1]
                if not np.isfinite(profile[-1]) or not np.all(np.isfinite(recent)):
                    continue
                recent_step = float(np.median(np.abs(np.diff(recent))))
                terminal_step = abs(float(profile[-1] - profile[-2]))
                if terminal_step > max(4.0, 3.0 * recent_step):
                    profile[-1] = float(np.median(recent))
                    terminal_adjusted = True
            if terminal_adjusted:
                section.warnings.append(
                    "器底付近の輪郭に孤立点があるため、末端半径を補正しました。"
                )
    valid = np.isfinite(raw_in) & np.isfinite(raw_out)
    if np.count_nonzero(valid) < 2:
        raise ValueError("内面・外面輪郭を行ごとに抽出できませんでした。")
    if not np.all(valid):
        missing_count = int(len(y_px) - np.count_nonzero(valid))
        missing = missing_count / len(y_px)
        if missing > 0.08:
            section.warnings.append(
                f"輪郭に欠損行があります（{missing_count}/{len(y_px)}行を補間）。"
            )
        indices = np.arange(len(y_px))
        raw_in[~valid] = np.interp(indices[~valid], indices[valid], raw_in[valid])
        raw_out[~valid] = np.interp(indices[~valid], indices[valid], raw_out[valid])

    r_in = _smooth(raw_in, smooth_window)
    r_out = _smooth(raw_out, smooth_window)
    r_in = np.maximum(r_in, 0.0)
    r_out = np.maximum(r_out, r_in + 0.25)
    if liquid_level_y is None:
        liquid_y = float(top)
    else:
        liquid_y = float(liquid_level_y)
        if not math.isfinite(liquid_y):
            raise ValueError("液面 y は有限な数値で指定してください")
        if liquid_y < top or liquid_y > bottom:
            section.warnings.append(
                f"液面 y={liquid_y:g} は器の範囲外です。{top}..{bottom} に制限します。"
            )
            liquid_y = float(np.clip(liquid_y, top, bottom))
    if section.mode == "lines":
        # Build a filled strip from the traced raw profiles for overlay and Pappus
        # moments. The radii themselves remain available in the smoothed arrays.
        area_mask = np.zeros_like(section.mask)
        for y_value, inner_radius, outer_radius in zip(y_px, r_in, r_out, strict=False):
            y_index = int(y_value)
            x0 = max(int(math.ceil(axis_x + inner_radius)), int(math.floor(axis_x)) + 1)
            x1 = max(x0, int(math.floor(axis_x + outer_radius)))
            if 0 <= y_index < area_mask.shape[0] and x0 < area_mask.shape[1]:
                area_mask[y_index, x0 : min(x1 + 1, area_mask.shape[1])] = 255
        section.mask = area_mask
    return Profiles(
        y_px, r_in, r_out, float(top), float(bottom), liquid_y, section.warnings
    )
