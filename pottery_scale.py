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


_SCALE_TEXT = re.compile(
    r"(?<![\d.])([0-9oil|]+(?:[.,][0-9oil|]+)?)(mm|cm|m)(?![a-z])",
    re.IGNORECASE,
)
_UNIT_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0}


def parse_metric_length(text: str) -> tuple[float, str, float] | None:
    """Parse a length such as ``10cm`` and return value, unit, and millimetres."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = normalized.replace("μ", "u").replace("µ", "u")
    normalized = re.sub(r"\s+", "", normalized)
    match = _SCALE_TEXT.search(normalized)
    if not match:
        return None

    number_text = match.group(1)
    for source, replacement in (("o", "0"), ("i", "1"), ("l", "1"), ("|", "1")):
        number_text = number_text.replace(source, replacement)
    number_text = number_text.replace(",", ".")
    try:
        value = float(number_text)
    except ValueError:
        return None
    unit = match.group(2).lower()
    length_mm = value * _UNIT_TO_MM[unit]
    if not math.isfinite(length_mm) or value <= 0:
        return None
    return value, unit, length_mm


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
        confidence = float(scores[index]) if scores is not None and index < len(scores) else 0.0
        candidates.append(
            ScaleTextCandidate(
                str(text), value, unit, length_mm, confidence, bounds
            )
        )
    return sorted(candidates, key=lambda item: item.confidence, reverse=True)


def detect_horizontal_scale_bars(
    image: np.ndarray,
    limit: int = 16,
    labels: list[ScaleTextCandidate] | None = None,
) -> list[ScaleBarCandidate]:
    """Find horizontal scale bars while ignoring strokes inside OCR labels."""
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    height, width = gray.shape[:2]
    if width < 3 or height < 3:
        return []

    # Adaptive thresholding handles faded rails and uneven paper lighting.
    edge_gray = gray
    if min(height, width) >= 3:
        filtered_gray = cv2.medianBlur(gray, 3)
    else:
        filtered_gray = gray
    block_size = max(15, (min(height, width) // 8) | 1)
    if block_size >= min(height, width):
        block_size = max(3, (min(height, width) - 1) | 1)
    adaptive = cv2.adaptiveThreshold(
        filtered_gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        block_size,
        7,
    )
    edges = cv2.Canny(edge_gray, 35, 120, apertureSize=3)
    min_length = max(24, int(width * 0.07))
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 360,
        threshold=max(16, int(min_length * 0.35)),
        minLineLength=min_length,
        maxLineGap=max(8, int(width * 0.025)),
    )
    candidates: list[ScaleBarCandidate] = []
    vertical_ticks: list[tuple[float, float, float]] = []
    segments = np.asarray(lines).reshape(-1, 4) if lines is not None else np.empty((0, 4))
    for raw in segments:
        x1, y1, x2, y2 = (float(value) for value in raw)
        if x2 < x1:
            x1, x2, y1, y2 = x2, x1, y2, y1
        dx, dy = x2 - x1, y2 - y1
        angle = abs(math.degrees(math.atan2(dy, dx)))
        if dx <= max(2.0, abs(dy) * 0.12) and abs(dy) >= max(6, height * 0.025):
            vertical_ticks.append(((x1 + x2) / 2, min(y1, y2), max(y1, y2)))
            continue
        if dx <= 0 or angle > 6:
            continue
        candidate = ScaleBarCandidate(x1, y1, x2, y2)
        if candidate.pixels < min_length:
            continue
        duplicate = False
        for existing_index, existing in enumerate(candidates):
            same_row = abs((candidate.y1 + candidate.y2) / 2 - (existing.y1 + existing.y2) / 2) <= max(3, height * 0.008)
            overlap = max(0.0, min(candidate.x2, existing.x2) - max(candidate.x1, existing.x1))
            shorter = min(candidate.pixels, existing.pixels)
            if same_row and shorter > 0 and overlap / shorter >= 0.75:
                duplicate = True
                if candidate.pixels > existing.pixels:
                    candidates[existing_index] = candidate
                break
        if not duplicate:
            candidates.append(candidate)

    # Horizontal opening catches low-contrast rails and bridges tiny gaps that
    # Hough often splits into several partial segments.
    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(12, min(80, width // 24)), 1)
    )
    horizontal_mask = cv2.morphologyEx(adaptive, cv2.MORPH_OPEN, horizontal_kernel)
    count, _, stats, centroids = cv2.connectedComponentsWithStats(
        horizontal_mask, connectivity=8
    )
    for component in range(1, count):
        x, y, component_width, component_height, area = stats[component]
        if component_width < min_length or component_height > max(8, height * 0.02):
            continue
        if area < component_width * 0.25:
            continue
        candidate = ScaleBarCandidate(
            float(x), float(centroids[component][1]),
            float(x + component_width - 1), float(centroids[component][1]),
        )
        duplicate = False
        for index, existing in enumerate(candidates):
            same_row = abs(candidate.y1 - (existing.y1 + existing.y2) / 2) <= max(3, height * 0.008)
            overlap = max(0.0, min(candidate.x2, existing.x2) - max(candidate.x1, existing.x1))
            shorter = min(candidate.pixels, existing.pixels)
            if same_row and shorter > 0 and overlap / shorter >= 0.65:
                duplicate = True
                if candidate.pixels > existing.pixels:
                    candidates[index] = candidate
                break
        if not duplicate:
            candidates.append(candidate)

    vertical_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (1, max(8, min(80, height // 30)))
    )
    vertical_mask = cv2.morphologyEx(adaptive, cv2.MORPH_OPEN, vertical_kernel)
    tick_count, _, tick_stats, tick_centroids = cv2.connectedComponentsWithStats(
        vertical_mask, connectivity=8
    )
    for component in range(1, tick_count):
        x, y, tick_width, tick_height, _area = tick_stats[component]
        if tick_height >= max(6, height * 0.025) and tick_width <= max(8, width * 0.02):
            vertical_ticks.append(
                (
                    float(tick_centroids[component][0]),
                    float(y),
                    float(y + tick_height - 1),
                )
            )

    # Extend detected horizontal strokes to nearby endpoint ticks. In scanned
    # rulers, the horizontal rail can stop just short of the full-height marks.
    refined: list[ScaleBarCandidate] = []
    for candidate in candidates:
        y_center = (candidate.y1 + candidate.y2) / 2
        tick_tolerance = max(8.0, min(width * 0.05, candidate.pixels * 0.08))

        def snap_endpoint(
            x: float,
            y_center: float = y_center,
            tick_tolerance: float = tick_tolerance,
        ) -> tuple[float, bool]:
            possible: list[tuple[float, float]] = []
            for tick_x, tick_y0, tick_y1 in vertical_ticks:
                x_distance = abs(tick_x - x)
                if x_distance > tick_tolerance:
                    continue
                vertical_gap = max(tick_y0 - y_center, 0.0, y_center - tick_y1)
                if vertical_gap <= max(4.0, height * 0.015):
                    possible.append((x_distance + vertical_gap * 0.5, tick_x))
            if not possible:
                return x, False
            return min(possible)[1], True

        sx1, left_tick = snap_endpoint(candidate.x1)
        sx2, right_tick = snap_endpoint(candidate.x2)
        if sx2 < sx1:
            sx1, sx2 = sx2, sx1

        def refine_rail_endpoint(
            x: float,
            is_start: bool,
            candidate: ScaleBarCandidate = candidate,
        ) -> float:
            """Tighten an unticked endpoint to the local dark-pixel transition."""
            margin = max(5, min(18, int(candidate.pixels * 0.025)))
            left = max(0, int(math.floor(x)) - margin)
            right = min(width - 1, int(math.ceil(x)) + margin)
            xs = np.arange(left, right + 1)
            if len(xs) < 4:
                return x
            line_y = np.interp(
                xs,
                [candidate.x1, candidate.x2],
                [candidate.y1, candidate.y2],
            )
            support = np.zeros(len(xs), dtype=float)
            for index, (px, py) in enumerate(zip(xs, line_y, strict=False)):
                iy = int(round(py))
                y0, y1 = max(0, iy - 2), min(height, iy + 3)
                if y1 > y0:
                    support[index] = float(np.mean(adaptive[y0:y1, px] > 0))
            active = support >= 0.25
            anchor = int(np.argmin(np.abs(xs - x)))
            candidates_active = np.flatnonzero(active)
            if not len(candidates_active):
                return x
            # Stay on the component touching the detected endpoint; a nearby
            # text stroke or second rail must not pull the measured endpoint.
            closest = int(candidates_active[np.argmin(np.abs(candidates_active - anchor))])
            if abs(int(xs[closest]) - x) > 4:
                return x
            run_start = closest
            run_end = closest
            while run_start > 0 and active[run_start - 1]:
                run_start -= 1
            while run_end + 1 < len(active) and active[run_end + 1]:
                run_end += 1
            if run_end - run_start < 2:
                return x
            threshold = 0.25
            if is_start and run_start > 0:
                before, after = support[run_start - 1], support[run_start]
                fraction = (threshold - before) / max(after - before, 1e-6)
                return float(xs[run_start - 1] + np.clip(fraction, 0, 1))
            if not is_start and run_end + 1 < len(xs):
                before, after = support[run_end], support[run_end + 1]
                fraction = (before - threshold) / max(before - after, 1e-6)
                return float(xs[run_end] + np.clip(fraction, 0, 1))
            return float(xs[run_start] if is_start else xs[run_end])

        if not left_tick:
            sx1 = refine_rail_endpoint(sx1, True)
        if not right_tick:
            sx2 = refine_rail_endpoint(sx2, False)
        if sx2 < sx1:
            sx1, sx2 = sx2, sx1
        # Measure center-band continuity; dark surroundings alone do not score
        # as a rail, so this also rejects short text strokes and paper texture.
        sample_x = np.linspace(sx1, sx2, num=min(160, max(24, int(sx2 - sx1))))
        sample_y = np.linspace(candidate.y1, candidate.y2, num=len(sample_x))
        support = []
        for px, py in zip(sample_x, sample_y, strict=False):
            ix, iy = int(round(px)), int(round(py))
            y0, y1 = max(0, iy - 2), min(height, iy + 3)
            x0, x1 = max(0, ix - 1), min(width, ix + 2)
            support.append(float(np.mean(gray[y0:y1, x0:x1])) < 175)
        continuity = float(np.mean(support)) if support else 0.0
        tick_support = int(left_tick) + int(right_tick)
        # Endpoint ticks are strong evidence that a long rail is a measured
        # scale bar. Give them enough weight that a thin but continuous rail
        # with both ticks can pass the conservative auto-apply threshold.
        confidence = min(1.0, 0.35 * continuity + 0.32 * tick_support + 0.10)
        refined.append(
            ScaleBarCandidate(sx1, candidate.y1, sx2, candidate.y2, confidence, tick_support)
        )

    if labels:
        text_regions = [
            (label.bounds, max(1.0, (label.bounds[3] - label.bounds[1]) * 0.08))
            for label in labels
        ]

        def overlaps_text(candidate: ScaleBarCandidate) -> bool:
            y_center = (candidate.y1 + candidate.y2) / 2
            for (x0, y0, x1, y1), y_padding in text_regions:
                if not (y0 - y_padding <= y_center <= y1 + y_padding):
                    continue
                overlap = max(0.0, min(candidate.x2, x1) - max(candidate.x1, x0))
                if overlap >= max(4.0, (x1 - x0) * 0.2):
                    return True
            return False

        refined = [candidate for candidate in refined if not overlaps_text(candidate)]

    candidates = refined
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
            ly0 - text_y_padding
            <= (bar.y1 + bar.y2) / 2
            <= ly1 + text_y_padding
            and max(0.0, min(bar.x2, lx1) - max(bar.x1, lx0))
            >= min_text_overlap
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


def has_confident_scale_match(
    labels: list[ScaleTextCandidate], bars: list[ScaleBarCandidate]
) -> bool:
    """Return true only when OCR and a single strong, nearby bar agree."""
    if not labels or not bars:
        return False

    confident_labels = [label for label in labels if label.confidence >= 0.60]
    if not confident_labels:
        return False

    plausible: list[ScaleBarCandidate] = []
    for bar in bars:
        if bar.confidence < 0.82 or bar.tick_support < 1:
            continue
        bar_y = (bar.y1 + bar.y2) / 2
        supported_by: list[ScaleTextCandidate] = []
        for label in confident_labels:
            lx0, ly0, lx1, ly1 = label.bounds
            if lx1 <= lx0 or ly1 <= ly0:
                continue
            label_width = max(1.0, lx1 - lx0)
            label_height = max(1.0, ly1 - ly0)
            if bar.pixels < max(24.0, label_width * 1.5):
                continue
            horizontal_gap = max(lx0 - bar.x2, bar.x1 - lx1, 0.0)
            vertical_gap = max(ly0 - bar_y, bar_y - ly1, 0.0)
            if horizontal_gap > max(32.0, label_width * 1.25):
                continue
            if vertical_gap > max(24.0, label_height * 2.0):
                continue
            supported_by.append(label)
        if supported_by:
            plausible.append(bar)

    if len(plausible) != 1 or plausible[0] != bars[0]:
        return False

    best_bar = plausible[0]
    bar_y = (best_bar.y1 + best_bar.y2) / 2
    supporting_labels: list[ScaleTextCandidate] = []
    for label in confident_labels:
        lx0, ly0, lx1, ly1 = label.bounds
        if lx1 <= lx0 or ly1 <= ly0:
            continue
        label_width = max(1.0, lx1 - lx0)
        label_height = max(1.0, ly1 - ly0)
        if best_bar.pixels < max(24.0, label_width * 1.5):
            continue
        horizontal_gap = max(lx0 - best_bar.x2, best_bar.x1 - lx1, 0.0)
        vertical_gap = max(ly0 - bar_y, bar_y - ly1, 0.0)
        if horizontal_gap <= max(32.0, label_width * 1.25) and vertical_gap <= max(24.0, label_height * 2.0):
            supporting_labels.append(label)

    distinct_lengths = {round(label.length_mm, 6) for label in supporting_labels}
    return len(distinct_lengths) == 1


def analyze_scale_candidates(
    image: np.ndarray,
) -> tuple[list[ScaleTextCandidate], list[ScaleBarCandidate]]:
    """Run OCR and line detection once and return candidates in score order."""
    try:
        labels = recognize_scale_text(image)
    except Exception:
        labels = []
    try:
        bars = detect_horizontal_scale_bars(image, labels=labels)
    except Exception:
        bars = []

    best_label = labels[0] if labels else None
    return labels, rank_scale_bars(bars, best_label, image.shape)


def extract_scale_from_image(
    image: np.ndarray,
) -> tuple[ScaleTextCandidate | None, ScaleBarCandidate | None, float | None]:
    """Extract (best_label, best_bar, mm_per_px) from a scale-bar image."""
    labels, bars = analyze_scale_candidates(image)
    best_label = labels[0] if labels else None
    best_bar = bars[0] if bars else None

    mm_per_px = None
    if best_label and best_bar and best_bar.pixels > 0:
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
    ) -> tuple[float, tuple[int, int] | None, list[ScaleTextCandidate], list[ScaleBarCandidate]]:
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
    pottery_path, scale_path, _, _ = classify_pottery_and_scale_with_candidates(path_a, path_b)
    return pottery_path, scale_path

