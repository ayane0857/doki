"""Preprocess scale images and locate horizontal bar candidates."""

from __future__ import annotations

import math

import cv2
import numpy as np

from doki.scale.matching import _MIN_CONFIDENT_BAR_CONFIDENCE, find_confident_scale_match
from doki.scale.models import ScaleBarCandidate, ScaleTextCandidate
from doki.scale.rails import _detect_in_aligned_mask


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
            ordered_pass_candidates = sorted(
                pass_candidates, key=candidate_quality, reverse=True
            )
            if find_confident_scale_match(labels, ordered_pass_candidates) is not None:
                break

    candidates.sort(
        key=lambda item: (
            item.confidence + 0.10 * item.tick_support,
            math.log1p(item.pixels),
        ),
        reverse=True,
    )
    return candidates[:limit]
