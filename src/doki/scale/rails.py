"""Identify and score rails and endpoint ticks in an aligned ink mask."""

from __future__ import annotations

import math

import cv2
import numpy as np


def _find_rails(
    mask: np.ndarray, min_length: int
) -> list[tuple[float, float, float, float, float]]:
    """Return (x1, x2, y, thickness, continuity) for long horizontal strokes/bars."""
    height, width = mask.shape[:2]
    gap = max(4, int(round(width * 0.01)))
    closed = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (gap, 1))
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
