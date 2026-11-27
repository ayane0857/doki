"""Load drawings and detect their rotation axis and wall section."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


@dataclass
class SectionResult:
    """Detected vessel wall section and its position in the source image."""

    mask: np.ndarray
    mode: str
    roi: tuple[int, int, int, int]
    warnings: list[str] = field(default_factory=list)
    closed_mask: np.ndarray | None = None
    contour_mask: np.ndarray | None = None


def parse_crop(value: str) -> tuple[int, int, int, int]:
    """Parse an image crop in x0,y0,x1,y1 form."""
    try:
        vals = tuple(int(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise ValueError("crop は x0,y0,x1,y1 の整数で指定してください") from exc
    if len(vals) != 4 or vals[2] <= vals[0] or vals[3] <= vals[1]:
        raise ValueError("crop は x0,y0,x1,y1 の順で、幅と高さが正である必要があります")
    return (vals[0], vals[1], vals[2], vals[3])


def parse_points(value: str) -> tuple[float, float, float, float]:
    """Parse two image points in x0,y0,x1,y1 form."""
    try:
        vals = tuple(float(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise ValueError("点は x0,y0,x1,y1 の数値で指定してください") from exc
    if len(vals) != 4:
        raise ValueError("点は x0,y0,x1,y1 の4値で指定してください")
    return (vals[0], vals[1], vals[2], vals[3])


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
    _, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    # Component 0 is the background; skip it.
    keep = np.where(stats[1:, cv2.CC_STAT_AREA] >= min_area)[0] + 1
    mask = np.isin(labels, keep)
    return (mask * 255).astype(np.uint8)


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
    center_band: np.ndarray = (binary[y_lo:y_hi, x_lo:x_hi] > 0).astype(np.uint8)
    # Bridge very short breaks in the axis before scoring each column.
    center_band = cv2.morphologyEx(
        center_band, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 5))
    )
    best_x = None
    best_score = -1.0
    best_run = 0
    expected_center = width / 2.0
    _CENTER_PENALTY_WEIGHT = 0.35  # Penalise columns far from the image centre.
    _CONTINUITY_WEIGHT = 0.08  # Reward dense columns with many foreground pixels.
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
        center_penalty = (
            abs(x - expected_center) / max(1, width) * _CENTER_PENALTY_WEIGHT
        )
        score = run + count * _CONTINUITY_WEIGHT - center_penalty * height
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
    from skimage.measure import label, regionprops

    labels = label(mask > 0, connectivity=2)  # type: ignore[no-untyped-call]
    props = regionprops(labels)  # type: ignore[no-untyped-call]
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
    from skimage.measure import label, regionprops

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

    enclosed_labels = label(enclosed > 0, connectivity=2)  # type: ignore[no-untyped-call]
    enclosed_props = regionprops(enclosed_labels)  # type: ignore[no-untyped-call]
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
        line_labels = np.asarray(label(line_source > 0, connectivity=2))  # type: ignore[no-untyped-call]
        line_props = regionprops(line_labels)  # type: ignore[no-untyped-call]
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
