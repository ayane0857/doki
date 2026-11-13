"""OCR and line detection helpers for image-based scale calibration."""

from __future__ import annotations

import math
from pathlib import Path
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

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

    number_text = match.group(1).translate(str.maketrans({"o": "0", "i": "1", "l": "1", "|": "1"}))
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
def _ocr_engine():
    """Create RapidOCR only when a user opens the calibration tool."""
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise RuntimeError(
            "OCRエンジンを読み込めません。RapidOCRとONNX Runtimeをインストールしてください。"
        ) from exc
    return RapidOCR()


def recognize_scale_text(image: np.ndarray) -> list[ScaleTextCandidate]:
    """Read metric length labels from an image using the bundled OCR engine."""
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
    image: np.ndarray, limit: int = 16
) -> list[ScaleBarCandidate]:
    """Find long, nearly horizontal strokes that could be scale bars."""
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    height, width = gray.shape[:2]
    if width < 2 or height < 2:
        return []

    edges = cv2.Canny(gray, 40, 130, apertureSize=3)
    min_length = max(24, int(width * 0.07))
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 360,
        threshold=max(16, int(min_length * 0.35)),
        minLineLength=min_length,
        maxLineGap=max(8, int(width * 0.025)),
    )
    if lines is None:
        return []

    candidates: list[ScaleBarCandidate] = []
    vertical_ticks: list[tuple[float, float, float]] = []
    segments = np.asarray(lines).reshape(-1, 4)
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

    # Extend detected horizontal strokes to nearby endpoint ticks. In scanned
    # rulers, the horizontal rail can stop just short of the full-height marks.
    tick_tolerance = max(8.0, width * 0.05)
    refined: list[ScaleBarCandidate] = []
    for candidate in candidates:
        y_center = (candidate.y1 + candidate.y2) / 2

        def snap_endpoint(x: float) -> float:
            possible: list[tuple[float, float]] = []
            for tick_x, tick_y0, tick_y1 in vertical_ticks:
                x_distance = abs(tick_x - x)
                if x_distance > tick_tolerance:
                    continue
                vertical_gap = max(tick_y0 - y_center, 0.0, y_center - tick_y1)
                if vertical_gap <= max(4.0, height * 0.025):
                    possible.append((x_distance + vertical_gap * 0.5, tick_x))
            return min(possible)[1] if possible else x

        sx1 = snap_endpoint(candidate.x1)
        sx2 = snap_endpoint(candidate.x2)
        if sx2 < sx1:
            sx1, sx2 = sx2, sx1
        refined.append(
            ScaleBarCandidate(
                sx1,
                candidate.y1,
                sx2,
                candidate.y2,
            )
        )

    candidates = refined
    candidates.sort(key=lambda item: item.pixels, reverse=True)
    return candidates[:limit]


def rank_scale_bars(
    bars: list[ScaleBarCandidate],
    label: ScaleTextCandidate | None,
    image_shape: tuple[int, ...],
) -> list[ScaleBarCandidate]:
    """Rank lines by length and proximity to a selected OCR label."""
    if label is None:
        return sorted(bars, key=lambda item: item.pixels, reverse=True)

    height, width = image_shape[:2]
    lx0, ly0, lx1, ly1 = label.bounds
    label_x = (lx0 + lx1) / 2
    label_y = (ly0 + ly1) / 2
    vertical_scale = max(16.0, height * 0.12)
    horizontal_scale = max(24.0, width * 0.12)

    def score(bar: ScaleBarCandidate) -> float:
        bar_y = (bar.y1 + bar.y2) / 2
        vertical = 1 / (1 + abs(bar_y - label_y) / vertical_scale)
        edge_distance = min(abs(label_x - bar.x1), abs(label_x - bar.x2))
        endpoint = 1 / (1 + edge_distance / horizontal_scale)
        if bar.x1 <= label_x <= bar.x2:
            endpoint = max(endpoint, 0.65)
        return bar.pixels * (0.7 + 0.5 * vertical + 0.3 * endpoint)

    return sorted(bars, key=score, reverse=True)


def extract_scale_from_image(
    image: np.ndarray,
) -> tuple[ScaleTextCandidate | None, ScaleBarCandidate | None, float | None]:
    """目盛り画像から (best_label, best_bar, mm_per_px) を自動抽出する。"""
    try:
        labels = recognize_scale_text(image)
    except Exception:
        labels = []
    try:
        bars = detect_horizontal_scale_bars(image)
    except Exception:
        bars = []

    best_label = labels[0] if labels else None
    ranked_bars = rank_scale_bars(bars, best_label, image.shape)
    best_bar = ranked_bars[0] if ranked_bars else None

    mm_per_px = None
    if best_label and best_bar and best_bar.pixels > 0:
        mm_per_px = best_label.length_mm / best_bar.pixels

    return best_label, best_bar, mm_per_px


def classify_pottery_and_scale(
    path_a: str | Path,
    path_b: str | Path,
) -> tuple[Path, Path]:
    """2つの画像パスから (pottery_image_path, scale_image_path) を判定して返す。"""
    from pottery_volume_core import read_image

    p_a = Path(path_a)
    p_b = Path(path_b)

    def compute_scale_score(path: Path) -> float:
        try:
            image = read_image(path)
        except Exception:
            return 0.0

        h, w = image.shape[:2]
        aspect_ratio = w / max(1.0, float(h))
        score = 0.0

        # 1. OCR単位付きテキスト（強力な目盛り特徴）
        try:
            labels = recognize_scale_text(image)
        except Exception:
            labels = []
        if labels:
            score += 35.0 + sum(label.confidence * 15.0 for label in labels)

        # 2. 水平スケールバーの検出
        try:
            bars = detect_horizontal_scale_bars(image)
        except Exception:
            bars = []
        if bars:
            score += 6.0
            if labels:
                ranked = rank_scale_bars(bars, labels[0], image.shape)
                if ranked:
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

        return score

    score_a = compute_scale_score(p_a)
    score_b = compute_scale_score(p_b)

    if score_a > score_b:
        return p_b, p_a  # bが土器、aが目盛り
    elif score_b > score_a:
        return p_a, p_b  # aが土器、bが目盛り
    else:
        # 同点の場合は面積（小さい方を目盛りとみなす）
        try:
            img_a = read_image(p_a)
            img_b = read_image(p_b)
            area_a = img_a.shape[0] * img_a.shape[1]
            area_b = img_b.shape[0] * img_b.shape[1]
            if area_a < area_b:
                return p_b, p_a
            else:
                return p_a, p_b
        except Exception:
            return p_a, p_b

