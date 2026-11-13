"""Core image analysis and volume calculations for pottery drawings."""

from __future__ import annotations

import argparse
import math
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
        raise argparse.ArgumentTypeError(
            "crop は x0,y0,x1,y1 の整数で指定してください"
        ) from exc
    if len(vals) != 4 or vals[2] <= vals[0] or vals[3] <= vals[1]:
        raise argparse.ArgumentTypeError(
            "crop は x0,y0,x1,y1 の順で、幅と高さが正である必要があります"
        )
    return vals  # type: ignore[return-value]


def parse_points(value: str) -> tuple[float, float, float, float]:
    """Parse two image points in x0,y0,x1,y1 form."""
    try:
        vals = tuple(float(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "点は x0,y0,x1,y1 の数値で指定してください"
        ) from exc
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


def write_image(path: Path, image: np.ndarray) -> None:
    """Write an image to a Unicode path on Windows and other platforms."""
    ext = path.suffix if path.suffix else ".png"
    success, encoded = cv2.imencode(ext, image)
    if not success:
        raise ValueError(f"画像をエンコードできません: {path}")
    try:
        encoded.tofile(str(path))
    except OSError as exc:
        raise ValueError(f"画像を保存できません: {path}") from exc


def remove_small_components(binary: np.ndarray, min_area: int = 5) -> np.ndarray:
    """Remove tiny isolated marks while retaining thin vessel outlines."""
    components = label(binary > 0, connectivity=2)
    cleaned = np.zeros(binary.shape, dtype=np.uint8)
    for region in regionprops(components):
        if region.area >= min_area:
            coords = region.coords
            cleaned[coords[:, 0], coords[:, 1]] = 255
    return cleaned


def detect_axis(
    binary: np.ndarray, override: float | None = None
) -> tuple[float, list[str]]:
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
        if len(indices) == 0:
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
    enclosed_height = max(
        (prop.bbox[2] - prop.bbox[0] for prop in enclosed_props), default=0
    )
    has_enclosed_section = enclosed_area >= max(
        20, int(roi_area * 0.002)
    ) and enclosed_height >= max(8, int(roi.shape[0] * 0.25))
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
            contours, _ = cv2.findContours(
                closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            if contours:
                contour = max(contours, key=cv2.contourArea)
                contour_area = cv2.contourArea(contour)
                if contour_area > enclosed_area * 1.15:
                    filled_contour = np.zeros_like(roi)
                    cv2.drawContours(
                        filled_contour, [contour], -1, 255, thickness=cv2.FILLED
                    )
                    section_roi = filled_contour
                    mode = "filled_contour"
                    warnings.append(
                        "ハッチ線で分断された閉領域を外側輪郭で補完しました。"
                    )
    else:
        if profile_mode == "filled":
            raise ValueError(
                "指定された filled モードで閉領域を検出できませんでした。断面線を確認してください。"
            )
        if profile_mode == "lines":
            warnings.append("指定により内面線・外面線の輪郭追跡モードを使用します。")
        else:
            warnings.append(
                "断面の閉領域を検出できず、線輪郭の追跡モードに切り替えました。"
            )
        # Trace long inner/outer outlines separately. This handles drawings where a
        # rim or foot is open by a pixel, and discards short hatch marks and labels.
        line_source = closed.copy()
        line_source[:, :3] = (
            0  # remove the long axis stroke and antialiased edge pixels
        )
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
            raise ValueError(
                "右側断面の輪郭が見つかりません。--axis-x / --crop を確認してください。"
            )

    section = np.zeros_like(binary)
    section[y0:y1, x0:x1] = section_roi
    closed_full = np.zeros_like(binary)
    closed_full[y0:y1, x0:x1] = closed
    return SectionResult(section, mode, (x0, y0, x1, y1), warnings, closed_full)


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
    return savgol_filter(
        values, window_length=win, polyorder=min(2, win - 1), mode="interp"
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
        for y, inner_radius, outer_radius in zip(y_px, r_in, r_out):
            x0 = max(int(math.ceil(axis_x + inner_radius)), int(math.floor(axis_x)) + 1)
            x1 = max(x0, int(math.floor(axis_x + outer_radius)))
            if 0 <= int(y) < area_mask.shape[0] and x0 < area_mask.shape[1]:
                area_mask[int(y), x0 : min(x1 + 1, area_mask.shape[1])] = 255
        section.mask = area_mask
    return Profiles(
        y_px, r_in, r_out, float(top), float(bottom), liquid_y, section.warnings
    )


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
    if len(y_fill) == 0:
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
            if (
                row < 0
                or row >= section_mask.shape[0]
                or (len(mask_rows) and row in mask_rows)
            ):
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
                "pappus_wall_volume_ml": pappus_px3 * volume_scale / 1000.0,
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
        inside = np.column_stack(
            (np.rint(axis_x + profiles.r_in_px).astype(int), profiles.y_px.astype(int))
        )
        outside = np.column_stack(
            (np.rint(axis_x + profiles.r_out_px).astype(int), profiles.y_px.astype(int))
        )
        cv2.polylines(overlay, [inside], False, (0, 0, 255), 1, cv2.LINE_AA)
        cv2.polylines(overlay, [outside], False, (255, 0, 0), 1, cv2.LINE_AA)
    cv2.line(
        overlay,
        (int(round(axis_x)), 0),
        (int(round(axis_x)), image.shape[0] - 1),
        (255, 80, 0),
        1,
    )
    cv2.line(
        overlay,
        (0, int(round(profiles.liquid_y_px))),
        (image.shape[1] - 1, int(round(profiles.liquid_y_px))),
        (0, 180, 255),
        1,
    )
    write_image(debug_dir / "detection_overlay.png", overlay)
    write_image(debug_dir / "section_mask.png", section.mask)
    if section.closed_mask is not None:
        write_image(debug_dir / "section_closed.png", section.closed_mask)

    factor = scale if scale is not None else 1.0
    axis_label = "radius (mm)" if scale is not None else "radius (px)"
    height_label = "height from rim (mm)" if scale is not None else "image y (px)"
    fig, ax = plt.subplots(figsize=(7, 5), dpi=140)
    ax.plot(
        profiles.r_in_px * factor,
        (profiles.y_px - profiles.top_y_px) * factor,
        label="inner profile",
    )
    ax.plot(
        profiles.r_out_px * factor,
        (profiles.y_px - profiles.top_y_px) * factor,
        label="outer profile",
    )
    ax.invert_yaxis()
    ax.set_xlabel(axis_label)
    ax.set_ylabel(height_label)
    ax.set_title("Pottery radial profiles")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(debug_dir / "profiles.png")
    plt.close(fig)
