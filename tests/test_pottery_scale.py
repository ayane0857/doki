"""Tests for OCR-driven metric scale calibration."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from pottery_scale import (
    classify_pottery_and_scale,
    detect_horizontal_scale_bars,
    extract_scale_from_image,
    parse_metric_length,
    rank_scale_bars,
    recognize_scale_text,
)
from pottery_volume_core import read_image


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("10cm", (10.0, "cm", 100.0)),
        ("50 mm", (50.0, "mm", 50.0)),
        ("1m", (1.0, "m", 1000.0)),
        ("１０ｃｍ", (10.0, "cm", 100.0)),
        ("lOcm", (10.0, "cm", 100.0)),
    ],
)
def test_parse_metric_length_and_convert_to_mm(text, expected):
    assert parse_metric_length(text) == expected


def test_parse_metric_length_rejects_missing_units_and_non_positive_values():
    assert parse_metric_length("10") is None
    assert parse_metric_length("0 cm") is None


def test_detect_horizontal_scale_bars_and_endpoint_ticks():
    image = np.full((120, 240, 3), 255, dtype=np.uint8)
    cv2.line(image, (20, 60), (220, 60), (0, 0, 0), 2)
    cv2.line(image, (20, 50), (20, 70), (0, 0, 0), 2)
    cv2.line(image, (220, 50), (220, 70), (0, 0, 0), 2)

    bars = detect_horizontal_scale_bars(image)

    assert bars
    assert bars[0].pixels == pytest.approx(200, abs=4)


def test_real_scale_image_reads_ten_centimetres_and_scale_bar():
    image = read_image(Path(__file__).parent / "fixtures" / "image.png")

    labels = recognize_scale_text(image)
    scale_label = next(
        candidate
        for candidate in labels
        if candidate.value == 10 and candidate.unit == "cm"
    )
    bars = rank_scale_bars(
        detect_horizontal_scale_bars(image), scale_label, image.shape
    )

    assert bars
    assert bars[0].pixels == pytest.approx(436, abs=4)
    assert scale_label.length_mm == 100


def test_classify_pottery_and_scale_with_fixture_images():
    fixtures_dir = Path(__file__).parent / "fixtures"
    scale_path = fixtures_dir / "image.png"
    pottery_path = fixtures_dir / "スクリーンショット 2026-11-10 215707.png"

    # 順序を反転させてテスト
    p1, s1 = classify_pottery_and_scale(scale_path, pottery_path)
    assert p1 == pottery_path
    assert s1 == scale_path

    p2, s2 = classify_pottery_and_scale(pottery_path, scale_path)
    assert p2 == pottery_path
    assert s2 == scale_path


def test_extract_scale_from_image():
    fixtures_dir = Path(__file__).parent / "fixtures"
    scale_img = read_image(fixtures_dir / "image.png")

    label, bar, mm_per_px = extract_scale_from_image(scale_img)
    assert label is not None
    assert label.value == 10 and label.unit == "cm" and label.length_mm == 100
    assert bar is not None
    assert bar.pixels == pytest.approx(436, abs=6)
    assert mm_per_px == pytest.approx(100.0 / 436.0, abs=0.01)

