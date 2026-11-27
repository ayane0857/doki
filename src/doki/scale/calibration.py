"""Public API and workflows for image-based scale calibration."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from doki.scale.detection import detect_horizontal_scale_bars as detect_horizontal_scale_bars
from doki.scale.matching import (
    associate_label_with_bar as associate_label_with_bar,
)
from doki.scale.matching import (
    find_confident_scale_match as find_confident_scale_match,
)
from doki.scale.matching import (
    has_confident_scale_match as has_confident_scale_match,
)
from doki.scale.matching import (
    rank_scale_bars as rank_scale_bars,
)
from doki.scale.models import ScaleBarCandidate as ScaleBarCandidate
from doki.scale.models import ScaleTextCandidate as ScaleTextCandidate
from doki.scale.ocr import parse_metric_length as parse_metric_length
from doki.scale.ocr import recognize_scale_text as recognize_scale_text
from doki.scale.rails import _stack_rails as _stack_rails


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
    from doki.analysis.core import read_image

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
