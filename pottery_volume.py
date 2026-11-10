#!/usr/bin/env python3
"""Estimate a rotational pottery vessel's capacity and wall volume from a drawing."""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from scipy.integrate import trapezoid
from scipy.signal import savgol_filter
from skimage.measure import label, regionprops

@dataclass
class SectionResult:
    """Detected vessel wall section and its position in the source image."""

    mask: np.ndarray
    mode: str
    roi: tuple[int, int, int, int]
    warnings: list[str] = field(default_factory=list)
    closed_mask: np.ndarray | None = None


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


def parse_crop(value: str) -> tuple[int, int, int, int]:
    """Parse an image crop in x0,y0,x1,y1 form."""
    try:
        vals = tuple(int(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("crop は x0,y0,x1,y1 の整数で指定してください") from exc
    if len(vals) != 4 or vals[2] <= vals[0] or vals[3] <= vals[1]:
        raise argparse.ArgumentTypeError("crop は x0,y0,x1,y1 の順で、幅と高さが正である必要があります")
    return vals  # type: ignore[return-value]


def parse_points(value: str) -> tuple[float, float, float, float]:
    """Parse two image points in x0,y0,x1,y1 form."""
    try:
        vals = tuple(float(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("点は x0,y0,x1,y1 の数値で指定してください") from exc
    if len(vals) != 4:
        raise argparse.ArgumentTypeError("点は x0,y0,x1,y1 の4値で指定してください")
    return vals  # type: ignore[return-value]


def binarize_image(gray: np.ndarray, adaptive: bool = False) -> tuple[np.ndarray, str]:
    """Create a black-line foreground mask using Otsu or adaptive thresholding."""
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    fg_fraction = float(np.count_nonzero(otsu)) / otsu.size
    if adaptive or fg_fraction < 0.0005 or fg_fraction > 0.30:
        block = max(15, (min(gray.shape[:2]) // 8) | 1)
        if block >= min(gray.shape[:2]):
            block = max(3, (min(gray.shape[:2]) - 1) | 1)
        mask = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, block, 7
        )
        return mask, "adaptive"
    return otsu, "otsu"


def read_image(path: Path) -> np.ndarray:
    """Read an image from a Unicode path on Windows and other platforms."""
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError as exc:
        raise ValueError(f"画像を読み込めません: {path}") from exc
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"画像を読み込めません: {path}")
    return image


def remove_small_components(binary: np.ndarray, min_area: int = 5) -> np.ndarray:
    """Remove tiny isolated marks while retaining thin vessel outlines."""
    components = label(binary > 0, connectivity=2)
    cleaned = np.zeros(binary.shape, dtype=np.uint8)
    for region in regionprops(components):
        if region.area >= min_area:
            coords = region.coords
            cleaned[coords[:, 0], coords[:, 1]] = 255
    return cleaned


def detect_axis(binary: np.ndarray, override: float | None = None) -> tuple[float, list[str]]:
    """Find the central long vertical rotation line from column projections."""
    height, width = binary.shape
    warnings: list[str] = []
    if override is not None:
        if not 0 <= override < width:
            raise ValueError(f"--axis-x は 0 以上 {width - 1} 以下で指定してください")
        return float(override), warnings

    x_lo, x_hi = int(width * 0.28), max(int(width * 0.72), int(width * 0.28) + 1)
    y_lo, y_hi = int(height * 0.04), max(int(height * 0.96), int(height * 0.04) + 1)
    center_band = (binary[y_lo:y_hi, x_lo:x_hi] > 0).astype(np.uint8)
    # Bridge very short breaks in the axis before scoring each column.
    center_band = cv2.morphologyEx(
        center_band, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 5))
    )
    best_x = None
    best_score = -1.0
    best_run = 0
    expected_center = width / 2.0
    for local_x in range(center_band.shape[1]):
        col = center_band[:, local_x]
        indices = np.flatnonzero(col)
        if not len(indices):
            continue
        gaps = np.flatnonzero(np.diff(indices) > 1)
        starts = np.r_[indices[0], indices[gaps + 1]]
        ends = np.r_[indices[gaps], indices[-1]]
        run = int(np.max(ends - starts + 1))
        count = int(len(indices))
        x = x_lo + local_x
        center_penalty = abs(x - expected_center) / max(1, width) * 0.35
        score = run + count * 0.08 - center_penalty * height
        if score > best_score:
            best_score, best_x, best_run = score, x, run
    if best_x is None:
        warnings.append("回転軸が見つかりません。--axis-x で指定してください。")
        return width / 2.0, warnings
    if best_run < height * 0.30:
        warnings.append(
            f"回転軸の確度が低いです（最長垂直線 {best_run}px）。必要なら --axis-x で上書きしてください。"
        )
    return float(best_x), warnings


def _largest_component(mask: np.ndarray) -> tuple[np.ndarray, list[int]]:
    """Return the largest connected component and the other component sizes."""
    labels = label(mask > 0, connectivity=2)
    props = regionprops(labels)
    if not props:
        return np.zeros(mask.shape, dtype=np.uint8), []
    props.sort(key=lambda item: item.area, reverse=True)
    largest = props[0]
    result = (labels == largest.label).astype(np.uint8) * 255
    return result, [int(item.area) for item in props[1:]]


def extract_section(
    binary: np.ndarray,
    axis_x: float,
    crop: tuple[int, int, int, int] | None = None,
    closing_kernel: int = 3,
    profile_mode: str = "auto",
) -> SectionResult:
    """Close gaps and extract the largest enclosed wall section on the axis's right."""
    height, width = binary.shape
    # Keep the axis column in the flood-fill ROI: closed section outlines may meet
    # the axis at the vessel foot. Profile extraction excludes that axis stroke.
    x0 = max(0, int(math.floor(axis_x)))
    y0, x1, y1 = 0, width, height
    if crop is not None:
        cx0, cy0, cx1, cy1 = crop
        x0, y0, x1, y1 = max(x0, cx0), max(0, cy0), min(width, cx1), min(height, cy1)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("--crop の範囲に回転軸右側の断面がありません")
    roi = binary[y0:y1, x0:x1]
    k = max(1, int(closing_kernel))
    if k % 2 == 0:
        k += 1
    closed = cv2.morphologyEx(
        roi, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    )
    warnings: list[str] = []

    # Flood-fill exterior background from a padded border; enclosed regions are candidates.
    padded = cv2.copyMakeBorder(closed, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    flood = padded.copy()
    cv2.floodFill(flood, None, (0, 0), 127)
    holes = (flood[1:-1, 1:-1] == 0).astype(np.uint8) * 255
    enclosed, other_sizes = _largest_component(holes)
    enclosed_area = int(np.count_nonzero(enclosed))
    roi_area = roi.shape[0] * roi.shape[1]

    enclosed_labels = label(enclosed > 0, connectivity=2)
    enclosed_props = regionprops(enclosed_labels)
    enclosed_height = max((prop.bbox[2] - prop.bbox[0] for prop in enclosed_props), default=0)
    has_enclosed_section = (
        enclosed_area >= max(20, int(roi_area * 0.002))
        and enclosed_height >= max(8, int(roi.shape[0] * 0.25))
    )
    if has_enclosed_section and profile_mode != "lines":
        section_roi = enclosed
        mode = "filled"
        significant = [size for size in other_sizes if size >= enclosed_area * 0.05]
        if significant:
            warnings.append(
                f"閉領域が複数あります（最大 {enclosed_area}px、次点 {max(significant)}px）。最大領域を採用しました。"
            )
            # Hatching may split a true band into multiple holes. Its external contour is a
            # more complete estimate when several large enclosed regions are present.
            contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                contour = max(contours, key=cv2.contourArea)
                contour_area = cv2.contourArea(contour)
                if contour_area > enclosed_area * 1.15:
                    filled_contour = np.zeros_like(roi)
                    cv2.drawContours(filled_contour, [contour], -1, 255, thickness=cv2.FILLED)
                    section_roi = filled_contour
                    mode = "filled_contour"
                    warnings.append("ハッチ線で分断された閉領域を外側輪郭で補完しました。")
    else:
        if profile_mode == "lines":
            warnings.append("指定により内面線・外面線の輪郭追跡モードを使用します。")
        else:
            warnings.append("断面の閉領域を検出できず、線輪郭の追跡モードに切り替えました。")
        # Trace long inner/outer outlines separately. This handles drawings where a
        # rim or foot is open by a pixel, and discards short hatch marks and labels.
        line_source = closed.copy()
        line_source[:, :3] = 0  # remove the long axis stroke and antialiased edge pixels
        line_labels = label(line_source > 0, connectivity=2)
        line_props = regionprops(line_labels)
        min_span = max(8, int(roi.shape[0] * 0.20))
        long_labels = [
            prop.label
            for prop in line_props
            if prop.bbox[2] - prop.bbox[0] >= min_span and prop.area >= 8
        ]
        if long_labels:
            section_roi = (np.isin(line_labels, long_labels)).astype(np.uint8) * 255
        else:
            section_roi, _ = _largest_component(line_source)
        mode = "lines"
        if not np.count_nonzero(section_roi):
            raise ValueError("右側断面の輪郭が見つかりません。--axis-x / --crop を確認してください。")

    section = np.zeros_like(binary)
    section[y0:y1, x0:x1] = section_roi
    closed_full = np.zeros_like(binary)
    closed_full[y0:y1, x0:x1] = closed
    return SectionResult(section, mode, (x0, y0, x1, y1), warnings, closed_full)


def _smooth(values: np.ndarray, window: int) -> np.ndarray:
    """Apply a short Savitzky-Golay smoother when enough samples exist."""
    if window <= 2 or len(values) < 5:
        return values
    win = min(window if window % 2 else window - 1, len(values) if len(values) % 2 else len(values) - 1)
    if win < 5:
        return values
    return savgol_filter(values, window_length=win, polyorder=min(2, win - 1), mode="interp")


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
        raise ValueError("器壁輪郭の行数が足りません。検出条件または --crop を調整してください。")

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
            section.warnings.append("口縁付近の軸から伸びる横線を内面輪郭から除外しました。")
    valid = np.isfinite(raw_in) & np.isfinite(raw_out)
    if np.count_nonzero(valid) < 2:
        raise ValueError("内面・外面輪郭を行ごとに抽出できませんでした。")
    if not np.all(valid):
        missing_count = int(len(y_px) - np.count_nonzero(valid))
        missing = missing_count / len(y_px)
        if missing > 0.08:
            section.warnings.append(f"輪郭に欠損行があります（{missing_count}/{len(y_px)}行を補間）。")
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
        if liquid_y < top or liquid_y > bottom:
            section.warnings.append(
                f"液面 y={liquid_y:g} は器の範囲外です。{top}..{bottom} に制限します。"
            )
            liquid_y = float(np.clip(liquid_y, top, bottom))
    if section.mode == "lines":
        # Build a filled strip from the traced raw profiles for overlay and Pappus
        # moments. The radii themselves remain available in the smoothed arrays.
        area_mask = np.zeros_like(section.mask)
        for y, inner_radius, outer_radius in zip(y_px, r_in, r_out):
            x0 = max(int(math.ceil(axis_x + inner_radius)), int(math.floor(axis_x)) + 1)
            x1 = max(x0, int(math.floor(axis_x + outer_radius)))
            if 0 <= int(y) < area_mask.shape[0] and x0 < area_mask.shape[1]:
                area_mask[int(y), x0:min(x1 + 1, area_mask.shape[1])] = 255
        section.mask = area_mask
    return Profiles(y_px, r_in, r_out, float(top), float(bottom), liquid_y, section.warnings)


def _profile_at(y_px: np.ndarray, values: np.ndarray, y: float) -> float:
    """Linearly interpolate a radial profile at a requested image row."""
    return float(np.interp(y, y_px, values))


def compute_volumes(
    profiles: Profiles,
    section_mask: np.ndarray,
    axis_x: float,
    mm_per_px: float | None = None,
    section_mode: str = "filled",
) -> dict[str, Any]:
    """Integrate capacity and wall volume; cross-check wall volume using Pappus."""
    y = profiles.y_px
    rin = profiles.r_in_px
    rout = profiles.r_out_px
    level = profiles.liquid_y_px
    start_index = int(np.searchsorted(y, level, side="left"))
    y_fill = y[start_index:]
    rin_fill = rin[start_index:]
    if not len(y_fill):
        capacity_px3 = 0.0
    else:
        if y_fill[0] > level:
            y_fill = np.r_[level, y_fill]
            rin_fill = np.r_[_profile_at(y, rin, level), rin_fill]
        capacity_px3 = math.pi * float(trapezoid(rin_fill**2, y_fill))
    wall_px3 = math.pi * float(trapezoid(rout**2 - rin**2, y))

    if np.any(section_mask):
        region_labels = label(section_mask > 0, connectivity=2)
        props = regionprops(region_labels)
        largest = max(props, key=lambda item: item.area)
        largest_mask = region_labels == largest.label
        mask_rows = np.flatnonzero(np.any(largest_mask, axis=1))
        area_px2 = 0.0
        first_moment_px3 = 0.0
        side_correction = 1.0 if section_mode == "filled" else 0.0
        for row in mask_rows:
            xs = np.flatnonzero(largest_mask[row])
            row_area = float(len(xs)) + side_correction
            row_centroid_x = (float(xs[0]) + float(xs[-1])) / 2.0
            area_px2 += row_area
            first_moment_px3 += row_area * (row_centroid_x - axis_x)
        # The flood-filled interior omits the top and bottom contour strokes too.
        # Add those end rows from the already interpolated profiles when needed.
        for row in (int(round(profiles.top_y_px)), int(round(profiles.bottom_y_px))):
            if row < 0 or row >= section_mask.shape[0] or (len(mask_rows) and row in mask_rows):
                continue
            radius_in = _profile_at(profiles.y_px, rin, float(row))
            radius_out = _profile_at(profiles.y_px, rout, float(row))
            row_area = max(0.0, radius_out - radius_in)
            area_px2 += row_area
            first_moment_px3 += row_area * (radius_in + radius_out) / 2.0
        centroid_radius_px = first_moment_px3 / area_px2 if area_px2 else 0.0
        centroid_x_px = axis_x + centroid_radius_px
        pappus_px3 = 2.0 * math.pi * centroid_radius_px * area_px2
    else:
        area_px2 = centroid_x_px = centroid_radius_px = pappus_px3 = 0.0
    diff_pct = abs(pappus_px3 - wall_px3) / wall_px3 * 100 if wall_px3 else 0.0
    px_scale = mm_per_px if mm_per_px is not None else 1.0
    unit = "mm" if mm_per_px is not None else "px"
    volume_unit = "mm3" if mm_per_px is not None else "px3"
    volume_scale = px_scale**3
    length_scale = px_scale
    mouth_diameter = 2.0 * float(rin[0]) * length_scale
    max_diameter = 2.0 * float(np.max(rout)) * length_scale
    height = (profiles.bottom_y_px - profiles.top_y_px) * length_scale
    result: dict[str, Any] = {
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
        result.update(
            {
                "capacity_cm3": capacity_px3 * volume_scale / 1000.0,
                "capacity_ml": capacity_px3 * volume_scale / 1000.0,
                "wall_volume_cm3": wall_px3 * volume_scale / 1000.0,
                "wall_volume_ml": wall_px3 * volume_scale / 1000.0,
                "pappus_wall_volume_cm3": pappus_px3 * volume_scale / 1000.0,
            }
        )
    return result


def visualize(
    image: np.ndarray,
    axis_x: float,
    section: SectionResult,
    profiles: Profiles,
    scale: float | None,
    debug_dir: Path,
) -> None:
    """Save an annotated detection overlay, radial profile plot, and masks."""
    import os

    os.environ.setdefault("MPLCONFIGDIR", str(debug_dir / ".mplconfig"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    debug_dir.mkdir(parents=True, exist_ok=True)
    overlay = image.copy()
    if overlay.ndim == 2:
        overlay = cv2.cvtColor(overlay, cv2.COLOR_GRAY2BGR)
    overlay[section.mask > 0] = (40, 180, 80)
    if np.any(section.mask):
        # Draw detected profile traces as red inner and blue outer curves.
        inside = np.column_stack((np.rint(axis_x + profiles.r_in_px).astype(int), profiles.y_px.astype(int)))
        outside = np.column_stack((np.rint(axis_x + profiles.r_out_px).astype(int), profiles.y_px.astype(int)))
        cv2.polylines(overlay, [inside], False, (0, 0, 255), 1, cv2.LINE_AA)
        cv2.polylines(overlay, [outside], False, (255, 0, 0), 1, cv2.LINE_AA)
    cv2.line(overlay, (int(round(axis_x)), 0), (int(round(axis_x)), image.shape[0] - 1), (255, 80, 0), 1)
    cv2.line(
        overlay,
        (0, int(round(profiles.liquid_y_px))),
        (image.shape[1] - 1, int(round(profiles.liquid_y_px))),
        (0, 180, 255),
        1,
    )
    cv2.imwrite(str(debug_dir / "detection_overlay.png"), overlay)
    cv2.imwrite(str(debug_dir / "section_mask.png"), section.mask)
    if section.closed_mask is not None:
        cv2.imwrite(str(debug_dir / "section_closed.png"), section.closed_mask)

    factor = scale if scale is not None else 1.0
    axis_label = "radius (mm)" if scale is not None else "radius (px)"
    height_label = "height from rim (mm)" if scale is not None else "image y (px)"
    fig, ax = plt.subplots(figsize=(7, 5), dpi=140)
    ax.plot(profiles.r_in_px * factor, (profiles.y_px - profiles.top_y_px) * factor, label="inner profile")
    ax.plot(profiles.r_out_px * factor, (profiles.y_px - profiles.top_y_px) * factor, label="outer profile")
    ax.invert_yaxis()
    ax.set_xlabel(axis_label)
    ax.set_ylabel(height_label)
    ax.set_title("Pottery radial profiles")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(debug_dir / "profiles.png")
    plt.close(fig)


def resolve_scale(args: argparse.Namespace, profiles: Profiles) -> float | None:
    """Resolve one of direct, known-distance, or known-height scale inputs."""
    choices = [
        args.scale_mm_per_px is not None,
        args.scale_points is not None,
        args.scale_bar_px is not None,
        args.vessel_height_mm is not None,
    ]
    if sum(choices) > 1:
        raise ValueError(
            "スケール指定は --scale-mm-per-px / --scale-points / --scale-bar-px / --vessel-height-mm のいずれか1つです"
        )
    if args.scale_mm_per_px is not None:
        if args.scale_mm_per_px <= 0:
            raise ValueError("--scale-mm-per-px は正の値で指定してください")
        return float(args.scale_mm_per_px)
    if args.scale_points is not None:
        if args.scale_bar_mm is None or args.scale_bar_mm <= 0:
            raise ValueError("--scale-points を使う場合は正の --scale-bar-mm が必要です")
        x0, y0, x1, y1 = args.scale_points
        distance = math.hypot(x1 - x0, y1 - y0)
        if distance <= 0:
            raise ValueError("--scale-points の2点は異なる位置を指定してください")
        return float(args.scale_bar_mm / distance)
    if args.scale_bar_px is not None:
        if args.scale_bar_mm is None or args.scale_bar_mm <= 0 or args.scale_bar_px <= 0:
            raise ValueError("--scale-bar-px と --scale-bar-mm は正の値で両方指定してください")
        return float(args.scale_bar_mm / args.scale_bar_px)
    if args.vessel_height_mm is not None:
        measured_height_px = profiles.bottom_y_px - profiles.top_y_px
        if args.vessel_height_mm <= 0 or measured_height_px <= 0:
            raise ValueError("器高は正の値で指定してください")
        return float(args.vessel_height_mm / measured_height_px)
    if args.scale_bar_mm is not None:
        raise ValueError("--scale-bar-mm は --scale-bar-px または --scale-points と一緒に指定してください")
    return None


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="土器実測図から回転軸対称を仮定して容量と器壁体積を推定します。"
    )
    parser.add_argument("input", type=Path, help="入力画像 (PNG/JPEGなど)")
    parser.add_argument("--scale-mm-per-px", type=float, help="直接指定する mm/px")
    parser.add_argument("--scale-bar-px", type=float, help="既知スケール線の画像上の長さ (px)")
    parser.add_argument("--scale-bar-mm", type=float, help="既知スケール線の実寸 (mm)")
    parser.add_argument("--scale-points", type=parse_points, help="既知長の両端 x0,y0,x1,y1 (px)")
    parser.add_argument("--vessel-height-mm", type=float, help="器高の実寸からスケールを算出 (mm)")
    parser.add_argument("--axis-x", type=float, help="回転軸 x 座標を手動指定 (px)")
    parser.add_argument("--crop", type=parse_crop, help="断面検索範囲 x0,y0,x1,y1")
    parser.add_argument("--liquid-level-y", type=float, help="液面 y 座標 (px)。既定は口縁")
    parser.add_argument("--closing-kernel", type=int, default=3, help="隙間を閉じる形態学カーネルサイズ (px、既定 3)")
    parser.add_argument("--profile-mode", choices=("auto", "filled", "lines"), default="auto", help="断面抽出方式 (既定 auto)")
    parser.add_argument("--min-component-area", type=int, default=5, help="二値化後に残す最小連結成分面積 (px)")
    parser.add_argument("--smooth-window", type=int, default=5, help="輪郭平滑化窓 (奇数 px、0 で無効)")
    parser.add_argument("--adaptive-threshold", action="store_true", help="適応的二値化を強制")
    parser.add_argument("--debug-dir", type=Path, help="重ね合わせ画像、断面マスク、輪郭グラフの出力先")
    parser.add_argument("--json-out", type=Path, default=Path("result.json"), help="JSON 出力先 (既定: ./result.json)")
    return parser


def launch_gui(initial_image: str | Path | None = None) -> None:
    """Open a small desktop form for selecting an image and analysis settings."""
    import contextlib
    import io
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("土器体積推定")
    root.geometry("780x770")
    root.minsize(720, 680)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    image_var = tk.StringVar(value=str(initial_image or ""))
    scale_mode_var = tk.StringVar(value="px（スケール未指定）")
    direct_scale_var = tk.StringVar()
    bar_px_var = tk.StringVar()
    known_mm_var = tk.StringVar()
    points_var = tk.StringVar()
    vessel_height_var = tk.StringVar()
    axis_var = tk.StringVar()
    crop_var = tk.StringVar()
    liquid_var = tk.StringVar()
    kernel_var = tk.StringVar(value="3")
    min_area_var = tk.StringVar(value="5")
    smooth_var = tk.StringVar(value="5")
    profile_mode_var = tk.StringVar(value="auto")
    json_var = tk.StringVar()
    debug_var = tk.StringVar()
    save_debug_var = tk.BooleanVar(value=True)
    adaptive_var = tk.BooleanVar(value=False)

    outer = ttk.Frame(root, padding=12)
    outer.grid(row=0, column=0, sticky="nsew")
    outer.columnconfigure(1, weight=1)
    outer.rowconfigure(12, weight=1)

    ttk.Label(outer, text="入力画像").grid(row=0, column=0, sticky="w", pady=4)
    ttk.Entry(outer, textvariable=image_var).grid(row=0, column=1, sticky="ew", padx=6)

    def browse_image() -> None:
        chosen = filedialog.askopenfilename(
            title="土器実測図を選択",
            filetypes=[
                ("画像ファイル", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                ("すべてのファイル", "*.*"),
            ],
        )
        if chosen:
            image_var.set(chosen)
            image_path = Path(chosen)
            if not json_var.get().strip():
                json_var.set(str(image_path.parent / "result.json"))
            if not debug_var.get().strip():
                debug_var.set(str(image_path.parent / "debug_out"))

    ttk.Button(outer, text="画像を選択…", command=browse_image).grid(row=0, column=2, padx=4)

    scale_frame = ttk.LabelFrame(outer, text="スケール")
    scale_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=8)
    scale_frame.columnconfigure(1, weight=1)
    ttk.Label(scale_frame, text="指定方法").grid(row=0, column=0, sticky="w", padx=8, pady=4)
    scale_combo = ttk.Combobox(
        scale_frame,
        textvariable=scale_mode_var,
        values=(
            "px（スケール未指定）",
            "mm/px を直接指定",
            "スケール線の px と mm",
            "2点座標と既知 mm",
            "器高から換算",
        ),
        state="readonly",
        width=25,
    )
    scale_combo.grid(row=0, column=1, sticky="w", padx=6, pady=4)

    scale_entries: dict[str, ttk.Frame] = {}
    for key, label_text, variable, hint in (
        ("direct", "mm/px", direct_scale_var, "例: 0.5"),
        ("bar", "スケール線 (px, mm)", bar_px_var, "px"),
        ("points", "2点 x0,y0,x1,y1 と既知 mm", points_var, "例: 40,20,140,20"),
        ("height", "器高 (mm)", vessel_height_var, "例: 120"),
    ):
        row_frame = ttk.Frame(scale_frame)
        row_frame.columnconfigure(1, weight=1)
        ttk.Label(row_frame, text=label_text).grid(row=0, column=0, sticky="w", padx=(8, 6), pady=4)
        ttk.Entry(row_frame, textvariable=variable, width=20).grid(row=0, column=1, sticky="w", pady=4)
        ttk.Label(row_frame, text=hint).grid(row=0, column=2, sticky="w", padx=6)
        if key == "bar":
            ttk.Label(row_frame, text="実寸 mm").grid(row=0, column=3, sticky="w", padx=(10, 4))
            ttk.Entry(row_frame, textvariable=known_mm_var, width=12).grid(row=0, column=4, sticky="w", padx=4)
        elif key == "points":
            ttk.Label(row_frame, text="実寸 mm").grid(row=0, column=3, sticky="w", padx=(10, 4))
            ttk.Entry(row_frame, textvariable=known_mm_var, width=12).grid(row=0, column=4, sticky="w", padx=4)
        scale_entries[key] = row_frame

    def update_scale_rows(*_args: object) -> None:
        for frame in scale_entries.values():
            if frame.winfo_manager() == "grid":
                frame.grid_remove()
        selected = scale_mode_var.get()
        key = {
            "mm/px を直接指定": "direct",
            "スケール線の px と mm": "bar",
            "2点座標と既知 mm": "points",
            "器高から換算": "height",
        }.get(selected)
        if key:
            scale_entries[key].grid(row=1, column=0, columnspan=2, sticky="ew")

    scale_mode_var.trace_add("write", update_scale_rows)
    update_scale_rows()

    detection = ttk.LabelFrame(outer, text="自動検出の調整（必要な場合のみ）")
    detection.grid(row=2, column=0, columnspan=3, sticky="ew", pady=4)
    detection.columnconfigure(1, weight=1)

    def add_setting(row: int, title: str, variable: tk.StringVar, hint: str = "") -> None:
        ttk.Label(detection, text=title).grid(row=row, column=0, sticky="w", padx=8, pady=3)
        ttk.Entry(detection, textvariable=variable, width=30).grid(row=row, column=1, sticky="w", padx=6, pady=3)
        if hint:
            ttk.Label(detection, text=hint).grid(row=row, column=2, sticky="w", padx=6, pady=3)

    add_setting(0, "回転軸 x (px)", axis_var, "空欄なら自動検出")
    add_setting(1, "断面 crop x0,y0,x1,y1", crop_var, "空欄なら画像全体")
    add_setting(2, "液面 y (px)", liquid_var, "空欄なら口縁")

    options = ttk.Frame(detection)
    options.grid(row=3, column=0, columnspan=3, sticky="ew", padx=8, pady=5)
    ttk.Label(options, text="クロージング").pack(side="left")
    ttk.Entry(options, textvariable=kernel_var, width=5).pack(side="left", padx=(4, 14))
    ttk.Label(options, text="最小成分").pack(side="left")
    ttk.Entry(options, textvariable=min_area_var, width=5).pack(side="left", padx=(4, 14))
    ttk.Label(options, text="平滑化窓").pack(side="left")
    ttk.Entry(options, textvariable=smooth_var, width=5).pack(side="left", padx=(4, 14))
    ttk.Label(options, text="輪郭モード").pack(side="left")
    ttk.Combobox(
        options,
        textvariable=profile_mode_var,
        values=("auto", "filled", "lines"),
        state="readonly",
        width=9,
    ).pack(side="left", padx=4)
    ttk.Checkbutton(detection, text="適応的二値化を使う", variable=adaptive_var).grid(
        row=4, column=0, columnspan=2, sticky="w", padx=8, pady=4
    )

    output = ttk.LabelFrame(outer, text="出力")
    output.grid(row=3, column=0, columnspan=3, sticky="ew", pady=8)
    output.columnconfigure(1, weight=1)
    ttk.Label(output, text="JSON").grid(row=0, column=0, sticky="w", padx=8, pady=4)
    ttk.Entry(output, textvariable=json_var).grid(row=0, column=1, sticky="ew", padx=6)
    ttk.Checkbutton(output, text="デバッグ画像も保存", variable=save_debug_var).grid(
        row=1, column=0, sticky="w", padx=8, pady=4
    )
    ttk.Entry(output, textvariable=debug_var).grid(row=1, column=1, sticky="ew", padx=6)

    result_box = tk.Text(outer, height=10, wrap="word", state="disabled")
    result_box.grid(row=12, column=0, columnspan=3, sticky="nsew", pady=(8, 4))

    def show_text(value: str) -> None:
        result_box.configure(state="normal")
        result_box.delete("1.0", "end")
        result_box.insert("1.0", value)
        result_box.configure(state="disabled")

    def calculate() -> None:
        image_text = image_var.get().strip().strip('"')
        if not image_text:
            messagebox.showerror("画像が未指定です", "画像を選ぶか、画像のパスを入力してください。", parent=root)
            return
        image_path = Path(image_text)
        if not image_path.is_file():
            messagebox.showerror("画像が見つかりません", image_text, parent=root)
            return

        json_path = json_var.get().strip()
        if not json_path:
            json_path = str(image_path.parent / "result.json")
            json_var.set(json_path)
        command_args = [str(image_path)]
        mode = scale_mode_var.get()
        try:
            if mode == "mm/px を直接指定":
                command_args += ["--scale-mm-per-px", direct_scale_var.get().strip()]
            elif mode == "スケール線の px と mm":
                command_args += [
                    "--scale-bar-px",
                    bar_px_var.get().strip(),
                    "--scale-bar-mm",
                    known_mm_var.get().strip(),
                ]
            elif mode == "2点座標と既知 mm":
                command_args += [
                    "--scale-points",
                    points_var.get().strip(),
                    "--scale-bar-mm",
                    known_mm_var.get().strip(),
                ]
            elif mode == "器高から換算":
                command_args += ["--vessel-height-mm", vessel_height_var.get().strip()]
            if axis_var.get().strip():
                command_args += ["--axis-x", axis_var.get().strip()]
            if crop_var.get().strip():
                command_args += ["--crop", crop_var.get().strip()]
            if liquid_var.get().strip():
                command_args += ["--liquid-level-y", liquid_var.get().strip()]
            command_args += [
                "--closing-kernel",
                kernel_var.get().strip(),
                "--min-component-area",
                min_area_var.get().strip(),
                "--smooth-window",
                smooth_var.get().strip(),
                "--profile-mode",
                profile_mode_var.get(),
                "--json-out",
                json_path,
            ]
            if adaptive_var.get():
                command_args.append("--adaptive-threshold")
            if save_debug_var.get():
                debug_path = debug_var.get().strip() or str(image_path.parent / "debug_out")
                debug_var.set(debug_path)
                command_args += ["--debug-dir", debug_path]
        except Exception as exc:
            messagebox.showerror("設定を確認してください", str(exc), parent=root)
            return

        stdout_buffer, stderr_buffer = io.StringIO(), io.StringIO()
        calculate_button.configure(state="disabled")
        root.configure(cursor="watch")
        root.update_idletasks()
        try:
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                exit_code = main(command_args)
            if exit_code != 0:
                details = stderr_buffer.getvalue() or stdout_buffer.getvalue()
                show_text(details or "計算に失敗しました。設定を確認してください。")
                messagebox.showerror("計算できませんでした", "入力画像と検出設定を確認してください。", parent=root)
                return
            result = json.loads(Path(json_path).read_text(encoding="utf-8"))
            length_unit = result["units"]["length"]
            volume_unit = result["units"]["volume"]
            lines = [
                "推定結果",
                f"器高: {result['vessel_height']:.2f} {length_unit}",
                f"口径: {result['mouth_diameter']:.2f} {length_unit}",
                f"最大径: {result['maximum_diameter']:.2f} {length_unit}",
                f"容量: {result['capacity']:.2f} {volume_unit}",
                f"器壁体積: {result['wall_volume']:.2f} {volume_unit}",
                f"パップス検算との差: {result['pappus_difference_percent']:.2f}%",
            ]
            if "capacity_ml" in result:
                lines += [
                    f"容量: {result['capacity_ml']:.2f} mL",
                    f"器壁体積: {result['wall_volume_ml']:.2f} mL",
                ]
            lines += ["", f"JSON: {json_path}"]
            if save_debug_var.get():
                lines.append(f"デバッグ画像: {debug_var.get().strip()}")
            if result.get("warnings"):
                lines += ["", "警告:"]
                lines.extend(f"・{warning}" for warning in result["warnings"])
            show_text("\n".join(lines))
        except (Exception, SystemExit) as exc:
            show_text(f"エラー: {exc}\n\n{stderr_buffer.getvalue()}")
            messagebox.showerror("エラー", str(exc), parent=root)
        finally:
            root.configure(cursor="")
            calculate_button.configure(state="normal")

    buttons = ttk.Frame(outer)
    buttons.grid(row=13, column=0, columnspan=3, sticky="e", pady=6)
    calculate_button = ttk.Button(buttons, text="計算する", command=calculate)
    calculate_button.pack(side="left", padx=4)
    ttk.Button(buttons, text="閉じる", command=root.destroy).pack(side="left", padx=4)

    root.bind("<Return>", lambda _event: calculate())
    root.mainloop()


def _print_result(result: dict[str, Any], section_mode: str, warnings: list[str]) -> None:
    """Print a compact human-readable summary."""
    unit = result["units"]["length"]
    volume_unit = result["units"]["volume"]
    print("=== 土器体積推定 ===")
    print(f"器高: {result['vessel_height']:.2f} {unit}")
    print(f"口径: {result['mouth_diameter']:.2f} {unit}")
    print(f"最大径: {result['maximum_diameter']:.2f} {unit}")
    print(f"容量: {result['capacity']:.2f} {volume_unit}")
    print(f"器壁体積: {result['wall_volume']:.2f} {volume_unit}")
    if "capacity_ml" in result:
        print(f"容量: {result['capacity_cm3']:.2f} cm³ ({result['capacity_ml']:.2f} mL)")
        print(f"器壁体積: {result['wall_volume_cm3']:.2f} cm³ ({result['wall_volume_ml']:.2f} mL)")
    print(f"パップス検算: {result['pappus_wall_volume']:.2f} {volume_unit} (差 {result['pappus_difference_percent']:.2f}%)")
    print(f"断面抽出モード: {section_mode}")
    for warning in warnings:
        print(f"警告: {warning}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Run the image-to-volume CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.closing_kernel < 1 or args.min_component_area < 1:
        parser.error("カーネルと最小連結成分面積は 1 以上で指定してください")
    if args.smooth_window not in (0, 1, 2) and args.smooth_window % 2 == 0:
        parser.error("--smooth-window は奇数か 0 で指定してください")
    try:
        image = read_image(args.input)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        binary, threshold_method = binarize_image(gray, args.adaptive_threshold)
        binary = remove_small_components(binary, args.min_component_area)
        axis_x, warnings = detect_axis(binary, args.axis_x)
        section = extract_section(binary, axis_x, args.crop, args.closing_kernel, args.profile_mode)
        profiles = extract_profiles(section, axis_x, args.liquid_level_y, args.smooth_window)
        scale = resolve_scale(args, profiles)
        all_warnings = warnings + section.warnings
        if scale is None:
            all_warnings.append("スケール未指定のため、体積は px³ 単位です。実寸換算にはスケールを指定してください。")
        result = compute_volumes(profiles, section.mask, axis_x, scale, section.mode)
        result.update(
            {
                "input": str(args.input),
                "axis_x_px": axis_x,
                "section_roi": list(section.roi),
                "section_mode": section.mode,
                "threshold_method": threshold_method,
                "top_y_px": profiles.top_y_px,
                "bottom_y_px": profiles.bottom_y_px,
                "warnings": all_warnings,
            }
        )
        _print_result(result, section.mode, all_warnings)
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON: {args.json_out}")
        if args.debug_dir:
            visualize(image, axis_x, section, profiles, scale, args.debug_dir)
            print(f"デバッグ画像: {args.debug_dir}")
        return 0
    except (ValueError, OSError, cv2.error) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    if len(sys.argv) == 1:
        launch_gui()
    else:
        raise SystemExit(main())
