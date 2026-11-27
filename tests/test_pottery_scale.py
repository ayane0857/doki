"""Tests for OCR-driven metric scale calibration."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from doki.analysis.core import read_image
from doki.scale import calibration
from doki.scale import detection as scale_detection
from doki.scale import rails as scale_rails
from doki.scale.calibration import (
    ScaleBarCandidate,
    ScaleTextCandidate,
    analyze_scale_candidates,
    classify_pottery_and_scale,
    detect_horizontal_scale_bars,
    extract_scale_from_image,
    find_confident_scale_match,
    has_confident_scale_match,
    parse_metric_length,
    rank_scale_bars,
)


def _raw_rail(
    x1: int, x2: int, y: int, confidence: float, tick_support: int = 0
) -> tuple[float, float, float, float, float, int]:
    return float(x1), float(x2), float(y), confidence, 1.0, tick_support


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("10cm", (10.0, "cm", 100.0)),
        ("50 mm", (50.0, "mm", 50.0)),
        ("1m", (1.0, "m", 1000.0)),
        ("１０ｃｍ", (10.0, "cm", 100.0)),
        ("l0cm", (10.0, "cm", 100.0)),
        ("1Ocm", (10.0, "cm", 100.0)),
        ("1,5 cm", (1.5, "cm", 15.0)),
        ("0 5 10cm", (10.0, "cm", 100.0)),
    ],
)
def test_parse_metric_length_and_convert_to_mm(text, expected):
    assert parse_metric_length(text) == expected


@pytest.mark.parametrize("text", ["10", "0 cm", "lOcm", "aim", "il m", "10cmx"])
def test_parse_metric_length_rejects_invalid_or_ambiguous_text(text):
    assert parse_metric_length(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("5 cm -2 cm", (5.0, "cm", 50.0)),
        ("5 cm \u22122 cm", (5.0, "cm", 50.0)),
        ("5 cm \u2212 2 cm", (5.0, "cm", 50.0)),
        ("5 cm 2 cm", (2.0, "cm", 20.0)),
    ],
)
def test_parse_metric_length_ignores_negative_values_but_uses_last_positive(
    text, expected
):
    assert parse_metric_length(text) == expected


def test_detect_horizontal_scale_bars_and_endpoint_ticks():
    image = np.full((120, 240, 3), 255, dtype=np.uint8)
    cv2.line(image, (20, 60), (220, 60), (0, 0, 0), 2)
    cv2.line(image, (20, 50), (20, 70), (0, 0, 0), 2)
    cv2.line(image, (220, 50), (220, 70), (0, 0, 0), 2)

    bars = detect_horizontal_scale_bars(image)

    assert bars
    assert bars[0].pixels == pytest.approx(200, abs=4)


@pytest.mark.parametrize("connector_xs", [(), (20,), (120,), (220,), (20, 220)])
def test_stack_rails_merges_only_with_connecting_strokes(connector_xs):
    mask = np.zeros((60, 240), dtype=np.uint8)
    cv2.line(mask, (20, 20), (220, 20), 255, 1)
    cv2.line(mask, (20, 40), (220, 40), 255, 1)
    for x in connector_xs:
        cv2.line(mask, (x, 20), (x, 40), 255, 1)
    rails = [(20.0, 220.0, 20.0, 1.0, 0.9), (20.0, 220.0, 40.0, 1.0, 0.9)]

    stacked = calibration._stack_rails(rails, mask)

    assert len(stacked) == (1 if connector_xs else 2)


def test_stack_rails_rejects_high_occupancy_with_a_blank_gap():
    mask = np.zeros((60, 240), dtype=np.uint8)
    cv2.line(mask, (20, 20), (220, 20), 255, 1)
    cv2.line(mask, (20, 30), (220, 30), 255, 1)
    cv2.line(mask, (120, 22), (120, 28), 255, 1)
    rails = [(20.0, 220.0, 20.0, 1.0, 0.9), (20.0, 220.0, 30.0, 1.0, 0.9)]

    assert len(calibration._stack_rails(rails, mask)) == 2


def test_detector_skips_skew_preview_with_zero_rounded_height(monkeypatch):
    image = np.full((15, 40_000, 3), 255, dtype=np.uint8)
    preview_source_shapes = []
    original_estimate_skew = scale_detection._estimate_skew
    monkeypatch.setattr(
        scale_detection,
        "_dark_mask",
        lambda gray: np.zeros(gray.shape[:2], dtype=np.uint8),
    )

    def estimate_skew(mask):
        preview_source_shapes.append(mask.shape[:2])
        return original_estimate_skew(mask)

    monkeypatch.setattr(scale_detection, "_estimate_skew", estimate_skew)
    monkeypatch.setattr(
        scale_detection, "_detect_in_aligned_mask", lambda _mask, _min_length: []
    )

    assert detect_horizontal_scale_bars(image) == []
    assert len(preview_source_shapes) == 1
    preview_height, preview_width = preview_source_shapes[0]
    assert round(preview_height * min(1.0, 800.0 / preview_width)) == 0


def test_detector_skips_resize_when_scaled_crop_dimension_is_zero(monkeypatch):
    image = np.full((8, 100_000, 3), 255, dtype=np.uint8)
    monkeypatch.setattr(
        scale_detection.cv2,
        "resize",
        lambda *_args, **_kwargs: pytest.fail("resize called for a zero-sized crop"),
    )

    assert detect_horizontal_scale_bars(image) == []


def test_detector_filters_text_before_applying_limit_and_keeps_usable_first_pass(
    monkeypatch,
):
    image = np.full((100, 1_000, 3), 255, dtype=np.uint8)
    label = ScaleTextCandidate("10cm", 10, "cm", 100, 0.99, (100, 30, 180, 50))
    raw = [
        _raw_rail(110, 140, 40, 0.99),
        _raw_rail(125, 155, 40, 0.98),
        _raw_rail(100, 300, 80, 0.85, 1),
    ]
    min_lengths = []

    def detect(_mask, min_length):
        min_lengths.append(min_length)
        return raw

    monkeypatch.setattr(scale_detection, "_estimate_skew", lambda _mask: 0.0)
    monkeypatch.setattr(scale_detection, "_detect_in_aligned_mask", detect)

    bars = detect_horizontal_scale_bars(image, limit=1, labels=[label])

    assert min_lengths == [70]
    assert len(bars) == 1
    assert bars[0].pixels == pytest.approx(200)


def test_detector_retries_shorter_pass_when_text_filter_removes_all_candidates(
    monkeypatch,
):
    image = np.full((100, 1_000, 3), 255, dtype=np.uint8)
    label = ScaleTextCandidate("10cm", 10, "cm", 100, 0.99, (100, 30, 180, 50))
    text_rail = _raw_rail(110, 140, 40, 0.99)
    valid_rail = _raw_rail(100, 300, 80, 0.85, 1)
    min_lengths = []

    def detect(_mask, min_length):
        min_lengths.append(min_length)
        return [text_rail] if len(min_lengths) == 1 else [valid_rail]

    monkeypatch.setattr(scale_detection, "_estimate_skew", lambda _mask: 0.0)
    monkeypatch.setattr(scale_detection, "_detect_in_aligned_mask", detect)

    bars = detect_horizontal_scale_bars(image, limit=1, labels=[label])

    assert min_lengths == [70, 35]
    assert len(bars) == 1
    assert bars[0].pixels == pytest.approx(200)


def test_detector_merges_weak_first_pass_with_shorter_pass_and_deduplicates(
    monkeypatch,
):
    image = np.full((100, 1_000, 3), 255, dtype=np.uint8)
    weak_rail = _raw_rail(100, 300, 60, 0.45)
    stronger_duplicate = _raw_rail(101, 301, 60, 0.85, 1)
    shorter_rail = _raw_rail(400, 600, 80, 0.72)
    passes = [[weak_rail], [stronger_duplicate, shorter_rail]]
    min_lengths = []

    def detect(_mask, min_length):
        min_lengths.append(min_length)
        return passes[len(min_lengths) - 1]

    monkeypatch.setattr(scale_detection, "_estimate_skew", lambda _mask: 0.0)
    monkeypatch.setattr(scale_detection, "_detect_in_aligned_mask", detect)

    bars = detect_horizontal_scale_bars(image)

    assert min_lengths == [70, 35]
    assert len(bars) == 2
    assert bars[0].confidence == 0.85
    assert bars[0].tick_support == 1


def test_detector_checks_label_match_before_stopping_after_strong_first_pass(
    monkeypatch,
):
    image = np.full((100, 1_000, 3), 255, dtype=np.uint8)
    label = ScaleTextCandidate("10cm", 10, "cm", 100, 0.99, (100, 30, 180, 50))
    unrelated_rail = _raw_rail(400, 600, 80, 0.85, 1)
    matching_rail = _raw_rail(100, 300, 80, 0.85, 1)
    passes = [[unrelated_rail], [matching_rail]]
    min_lengths = []

    def detect(_mask, min_length):
        min_lengths.append(min_length)
        return passes[len(min_lengths) - 1]

    monkeypatch.setattr(scale_detection, "_estimate_skew", lambda _mask: 0.0)
    monkeypatch.setattr(scale_detection, "_detect_in_aligned_mask", detect)

    bars = detect_horizontal_scale_bars(image, labels=[label])

    assert min_lengths == [70, 35]
    assert len(bars) == 2
    assert any(bar.x1 == pytest.approx(100) for bar in bars)


def test_real_scale_image_reads_ten_centimetres_and_scale_bar():
    image = read_image(Path(__file__).parent / "fixtures" / "scale_image.png")

    labels, bars = analyze_scale_candidates(image)
    scale_label = next(
        (
            candidate
            for candidate in labels
            if candidate.value == 10 and candidate.unit == "cm"
        ),
        None,
    )

    assert scale_label is not None, f"Expected a 10 cm label; detected {labels!r}"
    assert bars
    assert bars[0].pixels == pytest.approx(436, abs=4), (
        f"Expected the fixture's 436 px scale bar; detected {[bar.pixels for bar in bars]}"
    )
    assert scale_label.length_mm == 100
    assert has_confident_scale_match(labels, bars)


def test_detect_horizontal_scale_bar_preserves_one_pixel_edge():
    image = np.full((120, 240, 3), 255, dtype=np.uint8)
    cv2.line(image, (20, 60), (220, 60), (0, 0, 0), 1)
    cv2.line(image, (20, 55), (20, 65), (0, 0, 0), 1)
    cv2.line(image, (220, 55), (220, 65), (0, 0, 0), 1)

    bars = detect_horizontal_scale_bars(image)

    assert bars
    assert bars[0].pixels >= 196


def test_close_rails_with_separate_endpoint_ticks_both_reach_matching(monkeypatch):
    mask = np.zeros((120, 260), dtype=np.uint8)
    rails = [
        (20.0, 220.0, 50.0, 1.0, 1.0),
        (20.0, 220.0, 53.0, 1.0, 1.0),
    ]
    ticks = [(20.0, 42.0, 48.0), (220.0, 55.0, 63.0)]
    monkeypatch.setattr(scale_rails, "_find_rails", lambda _mask, _min: rails)
    monkeypatch.setattr(scale_rails, "_find_ticks", lambda _mask: ticks)
    label = ScaleTextCandidate("10cm", 10, "cm", 100, 0.99, (15, 25, 55, 35))

    raw_bars = scale_rails._detect_in_aligned_mask(mask, 24)
    bars = [
        ScaleBarCandidate(x1, y, x2, y, confidence, tick_support)
        for x1, x2, y, confidence, _thickness, tick_support in raw_bars
    ]

    assert len(raw_bars) == 2
    assert [bar[-1] for bar in raw_bars] == [1, 1]
    assert all(bar.confidence >= 0.80 for bar in bars)
    assert find_confident_scale_match([label], bars) is None

    monkeypatch.setattr(scale_detection, "_estimate_skew", lambda _mask: 0.0)
    monkeypatch.setattr(
        scale_detection, "_detect_in_aligned_mask", lambda _mask, _min: raw_bars
    )
    detected = detect_horizontal_scale_bars(
        np.full(mask.shape, 255, dtype=np.uint8), labels=[label]
    )

    assert len(detected) == 2
    assert find_confident_scale_match([label], detected) is None


def test_rank_scale_bars_discards_text_strokes_and_prefers_nearby_bar():
    label = ScaleTextCandidate("10cm", 10, "cm", 100, 0.99, (40, 50, 80, 70))
    text_stroke = ScaleBarCandidate(45, 60, 75, 60, 0.99, 2)
    nearby_bar = ScaleBarCandidate(82, 85, 282, 85, 0.85, 1)
    distant_line = ScaleBarCandidate(300, 110, 600, 110, 0.99, 0)

    ranked = rank_scale_bars(
        [text_stroke, distant_line, nearby_bar], label, (160, 640, 3)
    )

    assert ranked[0] == nearby_bar
    assert text_stroke not in ranked


def test_analyze_scale_candidates_reranks_original_bars_and_reassociates_label(
    monkeypatch,
):
    label_10cm = ScaleTextCandidate("10cm", 10, "cm", 100, 0.99, (30, 20, 70, 40))
    label_5cm = ScaleTextCandidate("5cm", 5, "cm", 50, 0.80, (250, 20, 290, 40))
    bar_near_5cm = ScaleBarCandidate(250, 60, 450, 60, 0.90, 1)
    bar_near_10cm = ScaleBarCandidate(30, 60, 230, 60, 0.90, 1)
    detected_bars = [bar_near_5cm, bar_near_10cm]
    rank_inputs = []

    def rank(bars, label, _image_shape):
        rank_inputs.append((list(bars), label))
        if label is label_10cm:
            return [bar_near_5cm, bar_near_10cm]
        return [bar_near_10cm, bar_near_5cm]

    monkeypatch.setattr(
        calibration, "recognize_scale_text", lambda _image: [label_10cm, label_5cm]
    )
    monkeypatch.setattr(
        calibration,
        "detect_horizontal_scale_bars",
        lambda _image, labels=None: detected_bars,
    )
    monkeypatch.setattr(calibration, "rank_scale_bars", rank)

    labels, bars = analyze_scale_candidates(np.zeros((100, 500), dtype=np.uint8))

    assert rank_inputs == [
        (detected_bars, label_10cm),
        (detected_bars, label_5cm),
    ]
    assert bars[0] == bar_near_10cm
    assert labels[0] == label_10cm


def test_analyze_scale_candidates_keeps_first_ranking_when_label_is_unchanged(
    monkeypatch,
):
    label = ScaleTextCandidate("10cm", 10, "cm", 100, 0.99, (30, 20, 70, 40))
    bar = ScaleBarCandidate(30, 60, 230, 60, 0.90, 1)
    rank_calls = []
    monkeypatch.setattr(calibration, "recognize_scale_text", lambda _image: [label])
    monkeypatch.setattr(
        calibration, "detect_horizontal_scale_bars", lambda _image, labels=None: [bar]
    )
    monkeypatch.setattr(
        calibration,
        "rank_scale_bars",
        lambda bars, _label, _shape: (rank_calls.append(list(bars)) or [bar]),
    )

    labels, bars = analyze_scale_candidates(np.zeros((100, 500), dtype=np.uint8))

    assert rank_calls == [[bar]]
    assert labels == [label]
    assert bars == [bar]


def test_confident_match_rejects_conflicting_labels():
    label_10cm = ScaleTextCandidate("10cm", 10, "cm", 100, 0.99, (40, 50, 80, 70))
    label_5cm = ScaleTextCandidate("5cm", 5, "cm", 50, 0.95, (40, 50, 80, 70))
    bar = ScaleBarCandidate(20, 60, 120, 60, 0.95, 1)

    assert not has_confident_scale_match([label_10cm, label_5cm], [bar])


def test_confident_match_returns_supported_label_not_promoted_low_confidence_label():
    label_5cm = ScaleTextCandidate("5cm", 5, "cm", 50, 0.59, (190, 50, 220, 70))
    label_10cm = ScaleTextCandidate("10cm", 10, "cm", 100, 0.95, (260, 50, 300, 70))
    bar = ScaleBarCandidate(20, 60, 220, 60, 0.95, 1)
    labels = calibration.associate_label_with_bar([label_10cm, label_5cm], bar)

    assert labels[0] == label_5cm
    assert find_confident_scale_match(labels, [bar]) == (label_10cm, bar)
    assert has_confident_scale_match(labels, [bar])


def test_one_endpoint_rail_with_nearby_label_is_confident(monkeypatch):
    image = np.full((160, 320, 3), 255, dtype=np.uint8)
    cv2.line(image, (60, 90), (260, 90), (0, 0, 0), 2)
    cv2.line(image, (60, 78), (60, 102), (0, 0, 0), 2)
    label = ScaleTextCandidate("10cm", 10, "cm", 100, 0.99, (15, 45, 55, 65))
    monkeypatch.setattr(scale_detection, "_estimate_skew", lambda _mask: 0.0)

    bars = detect_horizontal_scale_bars(image, labels=[label])
    match = find_confident_scale_match([label], bars)

    assert match is not None
    assert match[1].tick_support == 1
    assert match[1].confidence >= 0.80


def test_confident_match_rejects_far_rail_when_closer_rail_fits_label():
    label = ScaleTextCandidate("10cm", 10, "cm", 100, 0.99, (100, 100, 140, 120))
    closer_rail = ScaleBarCandidate(100, 140, 300, 140, 0.79, 0)
    far_rail = ScaleBarCandidate(100, 170, 300, 170, 0.95, 1)
    far_rail_with_both_endpoints = ScaleBarCandidate(100, 170, 300, 170, 0.95, 2)

    assert find_confident_scale_match([label], [far_rail, closer_rail]) is None
    assert find_confident_scale_match(
        [label], [far_rail_with_both_endpoints, closer_rail]
    ) == (label, far_rail_with_both_endpoints)


def test_confident_match_rejects_plain_rule_without_endpoint_support():
    label = ScaleTextCandidate("10cm", 10, "cm", 100, 0.99, (40, 50, 80, 70))
    plain_rail = ScaleBarCandidate(20, 60, 220, 60, 0.99, 0)

    assert find_confident_scale_match([label], [plain_rail]) is None


def test_classify_pottery_and_scale_with_fixture_images():
    fixtures_dir = Path(__file__).parent / "fixtures"
    scale_path = fixtures_dir / "scale_image.png"
    pottery_path = fixtures_dir / "pottery_image.png"

    # 順序を反転させてテスト
    p1, s1 = classify_pottery_and_scale(scale_path, pottery_path)
    assert p1 == pottery_path
    assert s1 == scale_path

    p2, s2 = classify_pottery_and_scale(pottery_path, scale_path)
    assert p2 == pottery_path
    assert s2 == scale_path


def test_extract_scale_from_image_calculates_mm_per_pixel(monkeypatch):
    label_5cm = ScaleTextCandidate("5cm", 5, "cm", 50, 0.59, (190, 50, 220, 70))
    label_10cm = ScaleTextCandidate("10cm", 10, "cm", 100, 0.95, (260, 50, 300, 70))
    bar = ScaleBarCandidate(20, 60, 220, 60, 0.95, 1)
    labels = calibration.associate_label_with_bar([label_10cm, label_5cm], bar)
    monkeypatch.setattr(
        calibration,
        "analyze_scale_candidates",
        lambda _image: (labels, [bar]),
    )

    extracted_label, extracted_bar, mm_per_px = extract_scale_from_image(
        np.zeros((120, 240), dtype=np.uint8)
    )

    assert extracted_label == label_10cm
    assert extracted_bar == bar
    assert mm_per_px == pytest.approx(0.5)

