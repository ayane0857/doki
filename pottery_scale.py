"""OCR and line detection helpers for image-based scale calibration."""

from __future__ import annotations

import math
import re
import threading
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class ScaleTextCandidate:
    """An OCR text box containing a metric length."""

    text: str
    value: float
    unit: str
    length_mm: float
    confidence: float
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True)
class ScaleBarCandidate:
    """A detected straight horizontal line that may be a scale bar."""

    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float = 0.0
    tick_support: int = 0

    @property
    def pixels(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)


# A number directly followed by a unit. Whitespace is only allowed between the
# number and its unit, so "0 5 10cm" reads as 10 cm (not 510 cm).
_SCALE_TEXT = re.compile(
    r"(?<![\d.,])([+-]?\s*[0-9oil|]+(?:[.,][0-9oil|]+)?)\s*(mm|cm|m)(?![a-z])",
    re.IGNORECASE,
)
_UNIT_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0}
_MIN_CONFIDENT_BAR_CONFIDENCE = 0.80


def parse_metric_length(text: str) -> tuple[float, str, float] | None:
    """Parse a length such as ``10cm`` and return value, unit, and millimetres.

    When several lengths appear (``0 5 10cm``), the last one is used because a
    scale bar's full length is printed at its far end.
    """
    normalized = unicodedata.normalize("NFKC", text).replace("\u2212", "-").lower()
    normalized = normalized.replace("μ", "u").replace("µ", "u")
    best: tuple[float, str, float] | None = None
    for match in _SCALE_TEXT.finditer(normalized):
        number_text = "".join(match.group(1).split())
        if not any(char.isdigit() for char in number_text):
            continue  # "aim", "il m": OCR look-alike letters only
        for source, replacement in (("o", "0"), ("i", "1"), ("l", "1"), ("|", "1")):
            number_text = number_text.replace(source, replacement)
        number_text = number_text.replace(",", ".")
        try:
            value = float(number_text)
        except ValueError:
            continue
        unit = match.group(2).lower()
        length_mm = value * _UNIT_TO_MM[unit]
        if math.isfinite(length_mm) and value > 0:
            best = (value, unit, length_mm)
    return best


@lru_cache(maxsize=1)
def _ocr_engine() -> Any:
    """Create RapidOCR only when a user opens the calibration tool."""
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise RuntimeError(
            "OCRエンジンを読み込めません。RapidOCRとONNX Runtimeをインストールしてください。"
        ) from exc
    return RapidOCR()


_ocr_lock = threading.Lock()


def recognize_scale_text(image: np.ndarray) -> list[ScaleTextCandidate]:
    """Read metric length labels from an image using the bundled OCR engine."""
    with _ocr_lock:
        result = _ocr_engine()(image)
    texts = getattr(result, "txts", None)
    if texts is None:
        texts = ()
    boxes = getattr(result, "boxes", None)
    scores = getattr(result, "scores", None)
    candidates: list[ScaleTextCandidate] = []
    for index, text in enumerate(texts):
        parsed = parse_metric_length(str(text))
        if parsed is None:
            continue
        value, unit, length_mm = parsed
        if boxes is not None and index < len(boxes):
            points = np.asarray(boxes[index], dtype=float).reshape(-1, 2)
            x0, y0 = float(np.min(points[:, 0])), float(np.min(points[:, 1]))
            x1, y1 = float(np.max(points[:, 0])), float(np.max(points[:, 1]))
            bounds = (x0, y0, x1, y1)
        else:
            bounds = (0.0, 0.0, 0.0, 0.0)
        confidence = (
            float(scores[index]) if scores is not None and index < len(scores) else 0.0
        )
        candidates.append(
            ScaleTextCandidate(str(text), value, unit, length_mm, confidence, bounds)
        )
    return sorted(candidates, key=lambda item: item.confidence, reverse=True)


def _dark_mask(gray: np.ndarray) -> np.ndarray:
    """Return a 0/255 mask of ink-like pixels, robust to uneven lighting."""
    height, width = gray.shape[:2]
    work = gray
    if float(np.median(work)) < 110:  # light rails on a dark background
        work = 255 - work
    blurred = cv2.GaussianBlur(work, (3, 3), 0)
    short_side = min(height, width)
    block = max(15, (short_side // 6) | 1)
    if block >= short_side:
        block = max(3, (short_side - 1) | 1)
    adaptive = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, block, 8
    )
    # Reject paper texture: real ink is clearly darker than the paper level.
    paper = float(np.percentile(blurred, 90))
    ink = blurred < paper - 35
    return ((adaptive > 0) & ink).astype(np.uint8) * 255


def _estimate_skew(
    mask: np.ndarray, max_angle: float = 3.0, step: float = 0.2
) -> float:
    """Find the small rotation (degrees) that makes horizontal strokes row-aligned."""
    height, width = mask.shape[:2]
    factor = min(1.0, 800.0 / width)
    if factor < 1 and round(height * factor) == 0:
        return 0.0
    small = (
        cv2.resize(mask, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
        if factor < 1
        else mask
    )
    small_h, small_w = small.shape[:2]
    center = (small_w / 2.0, small_h / 2.0)
    best_angle, best_score, zero_score = 0.0, -1.0, 0.0
    for angle in np.arange(-max_angle, max_angle + 1e-9, step):
        matrix = cv2.getRotationMatrix2D(center, float(angle), 1.0)
        rotated = cv2.warpAffine(
            small, matrix, (small_w, small_h), flags=cv2.INTER_LINEAR
        )
        rows = (rotated > 100).sum(axis=1).astype(float)
        score = float(np.sum(rows * rows))
        if abs(angle) < 1e-9:
            zero_score = score
        if score > best_score:
            best_angle, best_score = float(angle), score
    # Only deskew when it clearly sharpens the row profile.
    if best_score < zero_score * 1.03:
        return 0.0
    return best_angle


def _find_rails(
    mask: np.ndarray, min_length: int
) -> list[tuple[float, float, float, float, float]]:
    """Return (x1, x2, y, thickness, continuity) for long horizontal strokes/bars."""
    height, width = mask.shape[:2]
    gap = max(4, int(round(width * 0.01)))
    closed = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (gap, 3))
    )
    # A 1-row opening removes ticks, text and vertical clutter, and leaves
    # rails; outlined/checkered bars stay as one connected ladder shape.
    opened = cv2.morphologyEx(
        closed,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (min_length, 1)),
    )
    count, _, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    near_rows = cv2.dilate(mask, np.ones((3, 1), np.uint8))
    found: list[tuple[float, float, float, float, float]] = []
    for index in range(1, count):
        x, y, comp_w, comp_h, _area = (int(v) for v in stats[index])
        if comp_w < min_length:
            continue
        if comp_h > max(12, height * 0.2) or comp_w < 8 * comp_h:
            continue
        band = near_rows[y : y + comp_h, x : x + comp_w] > 0
        row_cover = band.sum(axis=1) / float(comp_w)
        continuity = float(row_cover.max()) if len(row_cover) else 0.0
        found.append(
            (
                float(x),
                float(x + comp_w - 1),
                y + (comp_h - 1) / 2.0,
                float(comp_h),
                continuity,
            )
        )
    # After stacking, a real bar is still long and thin; a short, thick block
    # is typically a word's x-height band or a logo.
    return [
        rail for rail in _stack_rails(found, mask) if (rail[1] - rail[0]) >= 8 * rail[3]
    ]


def _has_vertical_connector(
    mask: np.ndarray,
    upper: tuple[float, float, float, float, float],
    lower: tuple[float, float, float, float, float],
) -> bool:
    if upper[2] > lower[2]:
        upper, lower = lower, upper

    height, width = mask.shape[:2]
    row_start = max(0, int(math.floor(upper[2] - upper[3] / 2.0)))
    row_end = min(height, int(math.ceil(lower[2] + lower[3] / 2.0)) + 1)
    col_start = max(0, int(math.ceil(max(upper[0], lower[0]) - 2)))
    col_end = min(width, int(math.floor(min(upper[1], lower[1]) + 2)) + 1)
    if row_end <= row_start or col_end <= col_start:
        return False

    region = (mask[row_start:row_end, col_start:col_end] > 0).astype(np.uint8)
    component_count, component_ids = cv2.connectedComponents(region, connectivity=8)
    if component_count <= 1:
        return False

    upper_start = max(0, int(math.floor(upper[2] - upper[3] / 2.0)) - row_start)
    upper_end = min(
        region.shape[0], int(math.ceil(upper[2] + upper[3] / 2.0)) + 1 - row_start
    )
    lower_start = max(0, int(math.floor(lower[2] - lower[3] / 2.0)) - row_start)
    lower_end = min(
        region.shape[0], int(math.ceil(lower[2] + lower[3] / 2.0)) + 1 - row_start
    )
    upper_ids = np.unique(component_ids[upper_start:upper_end])
    lower_ids = np.unique(component_ids[lower_start:lower_end])
    connected_ids = np.intersect1d(upper_ids[upper_ids > 0], lower_ids[lower_ids > 0])
    return bool(connected_ids.size)


def _stack_rails(
    rails: list[tuple[float, float, float, float, float]],
    mask: np.ndarray,
) -> list[tuple[float, float, float, float, float]]:
    """Join vertically adjacent rails with the same extent into one bar.

    Separated rails are joined only when a side or interior stroke connects them.
    """
    pending = sorted(rails, key=lambda r: r[2])
    merged: list[tuple[float, float, float, float, float]] = []
    for rail in pending:
        x1, x2, y, thick, cont = rail
        for index, (mx1, mx2, my, mthick, mcont) in enumerate(merged):
            overlap = max(0.0, min(x2, mx2) - max(x1, mx1))
            shorter = min(x2 - x1, mx2 - mx1)
            top = min(y - thick / 2.0, my - mthick / 2.0)
            bottom = max(y + thick / 2.0, my + mthick / 2.0)
            gap = (bottom - top) - (thick + mthick)
            if (
                shorter > 0
                and overlap / shorter >= 0.9
                and gap <= max(30.0, 0.05 * shorter)
                and (
                    gap <= 0
                    or _has_vertical_connector(
                        mask,
                        (mx1, mx2, my, mthick, mcont),
                        rail,
                    )
                )
            ):
                merged[index] = (
                    min(x1, mx1),
                    max(x2, mx2),
                    (top + bottom) / 2.0,
                    bottom - top,
                    max(cont, mcont),
                )
                break
        else:
            merged.append(rail)
    return merged


def _find_ticks(mask: np.ndarray) -> list[tuple[float, float, float]]:
    """Return (x_center, y_top, y_bottom) of short vertical strokes."""
    height, width = mask.shape[:2]
    kernel_h = max(8, min(80, height // 30))
    vertical = cv2.morphologyEx(
        mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, kernel_h))
    )
    count, _, stats, centroids = cv2.connectedComponentsWithStats(
        vertical, connectivity=8
    )
    ticks: list[tuple[float, float, float]] = []
    for index in range(1, count):
        x, y, tick_w, tick_h, _area = (int(v) for v in stats[index])
        if tick_h >= max(6, height * 0.025) and tick_w <= max(8, width * 0.02):
            ticks.append((float(centroids[index][0]), float(y), float(y + tick_h - 1)))
    return ticks


def _band_clutter(
    mask: np.ndarray, x1: float, x2: float, y: float, thickness: float
) -> float:
    """Fraction of columns with ink just above/below a rail.

    Real scale rails have clean surroundings (only a few ticks), whereas a
    baseline of text has ink over a large share of its width.
    """
    height = mask.shape[0]
    left, right = max(0, int(round(x1))), min(mask.shape[1], int(round(x2)) + 1)
    if right <= left:
        return 0.0
    band = int(np.clip(0.12 * (x2 - x1), 8, 30))
    half = thickness / 2.0
    worst = 0.0
    for lo, hi in (
        (y - half - 2 - band, y - half - 2),
        (y + half + 2, y + half + 2 + band),
    ):
        r0, r1 = max(0, int(round(lo))), min(height, int(round(hi)))
        if r1 > r0:
            worst = max(worst, float(np.mean(mask[r0:r1, left:right].any(axis=0))))
    return worst


def _has_edge_end(mask: np.ndarray, x_end: float, y: float, thickness: float) -> bool:
    """True when a thick bar ends in a full-height vertical edge (block/outline side)."""
    if thickness < 6:
        return False
    height, width = mask.shape[:2]
    r0 = max(0, int(round(y - thickness / 2.0)))
    r1 = min(height, int(round(y + thickness / 2.0)) + 1)
    c0, c1 = max(0, int(round(x_end)) - 2), min(width, int(round(x_end)) + 3)
    if r1 <= r0 or c1 <= c0:
        return False
    return float(np.mean(mask[r0:r1, c0:c1].any(axis=1))) >= 0.75


def _detect_in_aligned_mask(
    mask: np.ndarray, min_length: int
) -> list[tuple[float, float, float, float, float, int]]:
    """Return rail candidates as (x1, x2, y, confidence, thickness, tick_support)."""
    height, width = mask.shape[:2]
    rails = _find_rails(mask, min_length)
    ticks = _find_ticks(mask)
    results = []
    for x1, x2, y, thickness, continuity in rails:
        length = x2 - x1
        reach = max(3.0, thickness / 2.0 + 2.0)
        tolerance = max(6.0, min(length * 0.04, 24.0))

        def usable(
            tick: tuple[float, float, float], rail_y: float = y, tick_reach: float = reach
        ) -> bool:
            return tick[1] - tick_reach <= rail_y <= tick[2] + tick_reach

        def snap(x: float, snap_tolerance: float = tolerance) -> tuple[float, bool]:
            options = [
                (abs(tick[0] - x), tick[0])
                for tick in ticks
                if usable(tick) and abs(tick[0] - x) <= snap_tolerance
            ]
            return (min(options)[1], True) if options else (x, False)

        clutter = _band_clutter(mask, x1, x2, y, thickness)
        left_edge = _has_edge_end(mask, x1, y, thickness)
        right_edge = _has_edge_end(mask, x2, y, thickness)
        if clutter >= 0.25 and not (left_edge and right_edge):
            continue  # a text baseline or drawing detail, not a scale rail
        sx1, left_tick = snap(x1)
        sx2, right_tick = snap(x2)
        if not left_tick and left_edge:
            sx1, left_tick = x1, True
        if not right_tick and right_edge:
            sx2, right_tick = x2, True
        if sx2 - sx1 < min_length * 0.9:
            sx1, sx2, left_tick, right_tick = x1, x2, False, False
        interior = sum(
            1
            for tick in ticks
            if usable(tick) and sx1 + tolerance < tick[0] < sx2 - tolerance
        )
        tick_support = int(left_tick) + int(right_tick)
        continuity_score = float(np.clip((continuity - 0.75) / 0.22, 0.0, 1.0))
        confidence = 0.10 + 0.40 * continuity_score + 0.25 * tick_support
        if interior >= 2:
            confidence += 0.05
        if (sx2 - sx1) >= 20 * max(1.0, thickness):
            confidence += 0.05
        # Frames and page rules hug the image border; they are rarely the bar.
        margin = max(2.0, thickness)
        if y <= margin or y >= height - 1 - margin:
            confidence -= 0.50
        results.append(
            (sx1, sx2, y, float(np.clip(confidence, 0.0, 1.0)), thickness, tick_support)
        )
    results.sort(
        key=lambda r: (r[3] + 0.1 * r[5], math.log1p(r[1] - r[0])), reverse=True
    )
    return results


def detect_horizontal_scale_bars(
    image: np.ndarray,
    limit: int = 16,
    labels: list[ScaleTextCandidate] | None = None,
) -> list[ScaleBarCandidate]:
    """Find horizontal scale bars (thin rails, ruler lines, outlined/checkered bars).

    The image is deskewed by up to +-3 degrees, converted to an ink mask, and
    long horizontal structures are extracted. End ticks are used to snap the
    measured endpoints, and strokes inside OCR labels are ignored.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    if gray.dtype != np.uint8:
        gray = cv2.normalize(
            gray, np.empty_like(gray), 0, 255, cv2.NORM_MINMAX
        ).astype(np.uint8)
    height, width = gray.shape[:2]
    if width < 32 or height < 8:
        return []

    shrink = min(1.0, 4000.0 / max(width, height))
    if shrink < 1.0 and (
        round(width * shrink) == 0 or round(height * shrink) == 0
    ):
        return []
    work = (
        cv2.resize(gray, None, fx=shrink, fy=shrink, interpolation=cv2.INTER_AREA)
        if shrink < 1
        else gray
    )
    work_h, work_w = work.shape[:2]

    angle = _estimate_skew(_dark_mask(work))
    center = (work_w / 2.0, work_h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    if angle:
        aligned_gray = cv2.warpAffine(
            work,
            matrix,
            (work_w, work_h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
    else:
        aligned_gray = work
    inverse = cv2.invertAffineTransform(matrix)
    mask = _dark_mask(aligned_gray)

    text_regions = [
        (label.bounds, max(1.0, (label.bounds[3] - label.bounds[1]) * 0.08))
        for label in labels or []
    ]

    def overlaps_text(candidate: ScaleBarCandidate) -> bool:
        y_center = (candidate.y1 + candidate.y2) / 2
        for (x0, y0, x1, y1), y_padding in text_regions:
            if not (y0 - y_padding <= y_center <= y1 + y_padding):
                continue
            overlap = max(0.0, min(candidate.x2, x1) - max(candidate.x1, x0))
            if (
                overlap >= max(4.0, (x1 - x0) * 0.2)
                and candidate.pixels < (x1 - x0) * 3
            ):
                return True
        return False

    candidates: list[ScaleBarCandidate] = []

    def candidate_quality(candidate: ScaleBarCandidate) -> tuple[float, float]:
        return (
            candidate.confidence + 0.10 * candidate.tick_support,
            math.log1p(candidate.pixels),
        )

    def same_rail(left: ScaleBarCandidate, right: ScaleBarCandidate) -> bool:
        left_x1, left_x2 = sorted((left.x1, left.x2))
        right_x1, right_x2 = sorted((right.x1, right.x2))
        overlap = max(0.0, min(left_x2, right_x2) - max(left_x1, right_x1))
        shorter = min(left.pixels, right.pixels)
        y_left = (left.y1 + left.y2) / 2
        y_right = (right.y1 + right.y2) / 2
        return (
            shorter > 0
            and overlap / shorter >= 0.98
            and abs(y_left - y_right) <= 0.5
        )

    for pass_index, fraction in enumerate((0.07, 0.035)):
        raw = _detect_in_aligned_mask(mask, max(24, int(work_w * fraction)))
        pass_candidates: list[ScaleBarCandidate] = []
        for sx1, sx2, y, confidence, _thickness, tick_support in raw:
            points = np.array([[sx1, y, 1.0], [sx2, y, 1.0]]) @ inverse.T / shrink
            pass_candidates.append(
                ScaleBarCandidate(
                    float(points[0][0]),
                    float(points[0][1]),
                    float(points[1][0]),
                    float(points[1][1]),
                    confidence,
                    tick_support,
                )
            )

        pass_candidates = [
            candidate for candidate in pass_candidates if not overlaps_text(candidate)
        ]
        for candidate in pass_candidates:
            duplicate_index = next(
                (
                    index
                    for index, existing in enumerate(candidates)
                    if same_rail(candidate, existing)
                ),
                None,
            )
            if duplicate_index is None:
                candidates.append(candidate)
            elif candidate_quality(candidate) > candidate_quality(
                candidates[duplicate_index]
            ):
                candidates[duplicate_index] = candidate

        if pass_index == 0 and any(
            candidate.confidence >= _MIN_CONFIDENT_BAR_CONFIDENCE
            and candidate.tick_support >= 1
            for candidate in pass_candidates
        ):
            if not labels:
                break

    candidates.sort(
        key=lambda item: (
            item.confidence + 0.10 * item.tick_support,
            math.log1p(item.pixels),
        ),
        reverse=True,
    )
    return candidates[:limit]


def rank_scale_bars(
    bars: list[ScaleBarCandidate],
    label: ScaleTextCandidate | None,
    image_shape: tuple[int, ...],
) -> list[ScaleBarCandidate]:
    """Rank lines by length and proximity to a selected OCR label."""
    if label is None:
        return sorted(
            bars,
            key=lambda item: (
                item.confidence + 0.20 * item.tick_support,
                0.05 * math.log1p(item.pixels),
            ),
            reverse=True,
        )

    height, width = image_shape[:2]
    lx0, ly0, lx1, ly1 = label.bounds
    label_width = max(1.0, lx1 - lx0)
    label_height = max(1.0, ly1 - ly0)

    # When callers detect bars without passing OCR labels, strokes inside the
    # recognized text can still look like short horizontal rails. Exclude those
    # before proximity scoring so a line in "10cm" cannot outrank the ruler.
    text_y_padding = max(1.0, label_height * 0.08)
    min_text_overlap = max(4.0, label_width * 0.2)
    bars = [
        bar
        for bar in bars
        if not (
            ly0 - text_y_padding <= (bar.y1 + bar.y2) / 2 <= ly1 + text_y_padding
            and max(0.0, min(bar.x2, lx1) - max(bar.x1, lx0)) >= min_text_overlap
        )
    ]
    vertical_scale = max(16.0, label_height * 2.0, height * 0.02)
    horizontal_scale = max(24.0, label_width * 1.25, width * 0.02)

    def score(bar: ScaleBarCandidate) -> float:
        bar_y = (bar.y1 + bar.y2) / 2
        horizontal_gap = max(lx0 - bar.x2, bar.x1 - lx1, 0.0)
        vertical_gap = max(ly0 - bar_y, bar_y - ly1, 0.0)
        proximity = math.exp(
            -horizontal_gap / horizontal_scale - vertical_gap / vertical_scale
        )
        return (
            1.4 * bar.confidence
            + 0.5 * bar.tick_support
            + 2.0 * proximity
            + 0.02 * math.log1p(bar.pixels)
        )

    return sorted(bars, key=score, reverse=True)


def find_confident_scale_match(
    labels: list[ScaleTextCandidate], bars: list[ScaleBarCandidate]
) -> tuple[ScaleTextCandidate, ScaleBarCandidate] | None:
    """Return the confident OCR label and bar when exactly one pair agrees."""
    if not labels or not bars:
        return None

    confident_labels = [
        label
        for label in labels
        if label.confidence >= 0.60
        and math.isfinite(label.length_mm)
        and label.length_mm > 0
    ]
    if not confident_labels:
        return None

    def label_bar_gaps(
        label: ScaleTextCandidate, bar: ScaleBarCandidate
    ) -> tuple[float, float] | None:
        if not math.isfinite(bar.pixels) or bar.pixels <= 0:
            return None
        lx0, ly0, lx1, ly1 = label.bounds
        if lx1 <= lx0 or ly1 <= ly0 or not all(
            math.isfinite(value) for value in label.bounds
        ):
            return None
        label_width = max(1.0, lx1 - lx0)
        label_height = max(1.0, ly1 - ly0)
        if bar.pixels < max(24.0, label_width * 1.5):
            return None
        horizontal_gap = max(lx0 - bar.x2, bar.x1 - lx1, 0.0)
        vertical_gap = max(ly0 - (bar.y1 + bar.y2) / 2, (bar.y1 + bar.y2) / 2 - ly1, 0.0)
        if horizontal_gap > max(32.0, label_width * 1.25):
            return None
        if vertical_gap > max(24.0, label_height * 3.0):
            return None
        return horizontal_gap, vertical_gap

    plausible: list[tuple[ScaleBarCandidate, list[ScaleTextCandidate]]] = []
    for bar in bars:
        if (
            not math.isfinite(bar.confidence)
            or bar.confidence < _MIN_CONFIDENT_BAR_CONFIDENCE
            or bar.tick_support < 1
        ):
            continue
        supported_by: list[ScaleTextCandidate] = []
        ambiguous_far_match = False
        for label in confident_labels:
            gaps = label_bar_gaps(label, bar)
            if gaps is None:
                continue
            supported_by.append(label)
            if gaps[1] > 24.0 and bar.tick_support < 2:
                ambiguous_far_match = any(
                    other is not bar
                    and (other_gaps := label_bar_gaps(label, other)) is not None
                    and other_gaps[1] < gaps[1]
                    for other in bars
                )
                if ambiguous_far_match:
                    break
        if supported_by and not ambiguous_far_match:
            plausible.append((bar, supported_by))

    if len(plausible) != 1 or plausible[0][0] != bars[0]:
        return None

    best_bar, supporting_labels = plausible[0]

    distinct_lengths = {round(label.length_mm, 6) for label in supporting_labels}
    if len(distinct_lengths) != 1:
        return None
    return max(supporting_labels, key=lambda label: label.confidence), best_bar


def has_confident_scale_match(
    labels: list[ScaleTextCandidate], bars: list[ScaleBarCandidate]
) -> bool:
    """Return true only when OCR and a single strong, nearby bar agree."""
    return find_confident_scale_match(labels, bars) is not None


def associate_label_with_bar(
    labels: list[ScaleTextCandidate], bar: ScaleBarCandidate | None
) -> list[ScaleTextCandidate]:
    """Reorder labels so the one that belongs to ``bar`` comes first.

    OCR confidence alone can pick "5cm" for a 10 cm bar. A label that sits near
    the bar, especially centred on one of its ends (``0  5  10cm``), wins.
    """
    if bar is None or len(labels) < 2:
        return list(labels)
    bar_y = (bar.y1 + bar.y2) / 2.0

    def score(label: ScaleTextCandidate) -> float:
        x0, y0, x1, y1 = label.bounds
        if x1 <= x0 or y1 <= y0:
            return 0.5 * label.confidence
        label_w, label_h = x1 - x0, y1 - y0
        h_gap = max(x0 - bar.x2, bar.x1 - x1, 0.0)
        v_gap = max(y0 - bar_y, bar_y - y1, 0.0)
        proximity = math.exp(
            -h_gap / max(24.0, label_w * 1.25) - v_gap / max(16.0, label_h * 3.0)
        )
        centre = (x0 + x1) / 2.0
        end_distance = min(abs(centre - bar.x1), abs(centre - bar.x2))
        end_bonus = 0.4 if end_distance <= max(label_w, 0.15 * bar.pixels) else 0.0
        return 0.5 * label.confidence + proximity + end_bonus

    return sorted(labels, key=score, reverse=True)


def analyze_scale_candidates(
    image: np.ndarray,
) -> tuple[list[ScaleTextCandidate], list[ScaleBarCandidate]]:
    """Run OCR and line detection once and return candidates in score order."""
    try:
        labels = recognize_scale_text(image)
    except Exception:
        labels = []
    try:
        detected_bars = detect_horizontal_scale_bars(image, labels=labels)
    except Exception:
        detected_bars = []

    best_label = labels[0] if labels else None
    bars = rank_scale_bars(detected_bars, best_label, image.shape)
    # With the bar chosen, pick the label that actually belongs to it.
    labels = associate_label_with_bar(labels, bars[0] if bars else None)
    if labels and labels[0] is not best_label:
        bars = rank_scale_bars(detected_bars, labels[0], image.shape)
        labels = associate_label_with_bar(labels, bars[0] if bars else None)
    return labels, bars


def extract_scale_from_image(
    image: np.ndarray,
) -> tuple[ScaleTextCandidate | None, ScaleBarCandidate | None, float | None]:
    """Extract (best_label, best_bar, mm_per_px) from a scale-bar image."""
    labels, bars = analyze_scale_candidates(image)
    best_label = labels[0] if labels else None
    best_bar = bars[0] if bars else None

    mm_per_px = None
    match = find_confident_scale_match(labels, bars)
    if match is not None:
        best_label, best_bar = match
        mm_per_px = best_label.length_mm / best_bar.pixels

    return best_label, best_bar, mm_per_px


def classify_pottery_and_scale_with_candidates(
    path_a: str | Path,
    path_b: str | Path,
) -> tuple[Path, Path, list[ScaleTextCandidate], list[ScaleBarCandidate]]:
    """Classify an image pair and reuse the OCR/line results for the scale image."""
    from pottery_volume_core import read_image

    p_a = Path(path_a)
    p_b = Path(path_b)

    def compute_scale_score(
        path: Path,
    ) -> tuple[
        float, tuple[int, int] | None, list[ScaleTextCandidate], list[ScaleBarCandidate]
    ]:
        try:
            image = read_image(path)
        except Exception:
            return 0.0, None, [], []

        h, w = image.shape[:2]
        image_shape = (h, w)
        aspect_ratio = w / max(1.0, float(h))
        score = 0.0

        # 1. OCR単位付きテキスト（強力な目盛り特徴）
        labels, bars = analyze_scale_candidates(image)
        if labels:
            score += 35.0 + sum(label.confidence * 15.0 for label in labels)

        # 2. 水平スケールバーの検出
        if bars:
            score += 6.0
            if labels:
                score += 12.0

        # 3. アスペクト比（目盛りは横長、土器実測図は縦長〜正方形寄り）
        if aspect_ratio >= 3.0:
            score += 14.0
        elif aspect_ratio >= 2.0:
            score += 7.0
        elif aspect_ratio < 1.4:
            score -= 10.0

        # 4. ファイル名の補助判定
        name_lower = path.name.lower()
        scale_keywords = ("scale", "目盛", "bar", "ruler", "cm", "mm")
        pottery_keywords = ("pottery", "doki", "土器", "vessel", "section", "実測")
        if any(kw in name_lower for kw in scale_keywords):
            score += 10.0
        if any(kw in name_lower for kw in pottery_keywords):
            score -= 10.0

        # 枝番（-2 や _2 は目盛り、-1 や _1 は土器に用いられやすい傾向）
        if re.search(r"[-_]2\b", name_lower):
            score += 4.0
        elif re.search(r"[-_]1\b", name_lower):
            score -= 4.0

        return score, image_shape, labels, bars

    score_a, image_a, labels_a, bars_a = compute_scale_score(p_a)
    score_b, image_b, labels_b, bars_b = compute_scale_score(p_b)

    if score_a > score_b:
        return p_b, p_a, labels_a, bars_a
    elif score_b > score_a:
        return p_a, p_b, labels_b, bars_b
    else:
        # 同点の場合は面積（小さい方を目盛りとみなす）
        if image_a is None or image_b is None:
            return p_a, p_b, labels_b, bars_b
        area_a = image_a[0] * image_a[1]
        area_b = image_b[0] * image_b[1]
        if area_a < area_b:
            return p_b, p_a, labels_a, bars_a
        return p_a, p_b, labels_b, bars_b


def classify_pottery_and_scale(
    path_a: str | Path,
    path_b: str | Path,
) -> tuple[Path, Path]:
    """Return the classified pottery image path and scale image path."""
    pottery_path, scale_path, _, _ = classify_pottery_and_scale_with_candidates(
        path_a, path_b
    )
    return pottery_path, scale_path
