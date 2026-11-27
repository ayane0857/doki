"""Rank scale candidates and match OCR labels to their bars."""

from __future__ import annotations

import math

from doki.scale.models import ScaleBarCandidate, ScaleTextCandidate

_MIN_CONFIDENT_BAR_CONFIDENCE = 0.80


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
