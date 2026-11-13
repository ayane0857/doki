"""Synthetic integration tests for vessel volume estimation."""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from pottery_volume import (
    binarize_image,
    compute_volumes,
    detect_axis,
    extract_profiles,
    extract_section,
    main,
    read_image,
    remove_small_components,
    resolve_scale,
    write_image,
)
from pottery_volume_gui import build_tsv_row, build_tsv_table, pixel_distance


def run_pipeline(image: np.ndarray) -> tuple[dict, float]:
    """Run the same detection and volume steps as the CLI on a synthetic image."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary, _ = binarize_image(gray)
    binary = remove_small_components(binary, min_area=2)
    axis, axis_warnings = detect_axis(binary)
    assert not axis_warnings
    section = extract_section(binary, axis, closing_kernel=3)
    profiles = extract_profiles(section, axis, smooth_window=5)
    return compute_volumes(profiles, section.mask, axis, section_mode=section.mode), axis


def cylinder_shell(
    inner_radius: int = 54,
    outer_radius: int = 64,
    height: int = 160,
) -> np.ndarray:
    """Draw a right-side half-section of a cylindrical shell."""
    image = np.full((260, 360, 3), 255, dtype=np.uint8)
    axis, top = 180, 45
    bottom = top + height
    cv2.line(image, (axis, 5), (axis, 255), (0, 0, 0), 1)
    polygon = np.array(
        [
            [axis + inner_radius, top],
            [axis + outer_radius, top],
            [axis + outer_radius, bottom],
            [axis + inner_radius, bottom],
        ],
        dtype=np.int32,
    )
    cv2.polylines(image, [polygon], True, (0, 0, 0), 1)
    return image


def hemisphere_shell(
    inner_radius: int = 72,
    outer_radius: int = 80,
) -> np.ndarray:
    """Draw a right-half cross section of concentric hemispherical surfaces."""
    image = np.full((260, 360, 3), 255, dtype=np.uint8)
    axis, top = 180, 50
    theta_out = np.linspace(0, math.pi / 2, 180)
    outer = np.column_stack(
        (
            axis + outer_radius * np.cos(theta_out),
            top + outer_radius * np.sin(theta_out),
        )
    )
    theta_in = np.linspace(math.pi / 2, 0, 160)
    inner = np.column_stack(
        (
            axis + inner_radius * np.cos(theta_in),
            top + inner_radius * np.sin(theta_in),
        )
    )
    points = np.vstack(
        (
            outer,
            [axis, top + inner_radius],
            inner[1:],
            [axis + outer_radius, top],
        )
    )
    polygon = np.rint(points).astype(np.int32).reshape((-1, 1, 2))
    cv2.line(image, (axis, 5), (axis, 255), (0, 0, 0), 1)
    cv2.polylines(image, [polygon], True, (0, 0, 0), 1)
    return image


def low_resolution_cylinder_shell() -> np.ndarray:
    """Draw a small 270 by 170 pixel cylinder section."""
    image = np.full((170, 270, 3), 255, dtype=np.uint8)
    axis, top, inner_radius, outer_radius, height = 135, 22, 38, 45, 105
    bottom = top + height
    cv2.line(image, (axis, 3), (axis, 165), (0, 0, 0), 1)
    polygon = np.array(
        [
            [axis + inner_radius, top],
            [axis + outer_radius, top],
            [axis + outer_radius, bottom],
            [axis + inner_radius, bottom],
        ],
        dtype=np.int32,
    )
    cv2.polylines(image, [polygon], True, (0, 0, 0), 1)
    return image


@pytest.mark.parametrize(
    ("image_factory", "theory"),
    [
        (
            cylinder_shell,
            lambda: (
                math.pi * 54**2 * 160,
                math.pi * (64**2 - 54**2) * 160,
            ),
        ),
        (
            hemisphere_shell,
            lambda: (
                2 / 3 * math.pi * 72**3,
                2 / 3 * math.pi * (80**3 - 72**3),
            ),
        ),
    ],
)
def test_synthetic_capacity_and_wall_volume_within_five_percent(image_factory, theory):
    """Cylinder and hemisphere examples should be within 5% of analytic volumes."""
    result, axis = run_pipeline(image_factory())
    expected_capacity, expected_wall = theory()
    assert axis == pytest.approx(180, abs=1)
    assert result["capacity"] == pytest.approx(expected_capacity, rel=0.05)
    assert result["wall_volume"] == pytest.approx(expected_wall, rel=0.05)
    assert result["pappus_difference_percent"] < 5


def test_scale_conversion_is_cubic_and_reports_ml():
    """One mm per pixel reports cubic millimetres and millilitres."""
    image = cylinder_shell()
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary, _ = binarize_image(gray)
    section = extract_section(binary, 180)
    profiles = extract_profiles(section, 180)
    result = compute_volumes(profiles, section.mask, 180, mm_per_px=0.5, section_mode=section.mode)
    assert result["units"]["volume"] == "mm3"
    assert result["capacity_cm3"] == pytest.approx(result["capacity"] / 1000)
    assert result["capacity_ml"] == pytest.approx(result["capacity_cm3"])


def test_pixel_distance_returns_image_distance():
    """The GUI measurement helper reports the Euclidean pixel distance."""
    assert pixel_distance((10, 20), (13, 24)) == pytest.approx(5)


def test_low_resolution_270_by_170_image():
    """The automatic detector should retain accuracy on a small drawing."""
    result, axis = run_pipeline(low_resolution_cylinder_shell())
    expected = math.pi * 38**2 * 105
    expected_wall = math.pi * (45**2 - 38**2) * 105
    assert axis == pytest.approx(135, abs=1)
    assert result["capacity"] == pytest.approx(expected, rel=0.05)
    assert result["wall_volume"] == pytest.approx(expected_wall, rel=0.05)
    assert result["pappus_difference_percent"] < 5


@pytest.mark.parametrize(
    "option",
    ["--scale-mm-per-px", "--scale-bar-px", "--scale-bar-mm", "--vessel-height-mm"],
)
def test_scale_rejects_non_finite_values(option):
    """Scale inputs must not allow NaN or infinity into volume calculations."""
    args = SimpleNamespace(
        scale_mm_per_px=None,
        scale_points=None,
        scale_bar_px=None,
        scale_bar_mm=None,
        vessel_height_mm=None,
    )
    setattr(args, option.removeprefix("--").replace("-", "_"), math.nan)
    if option == "--scale-bar-px":
        args.scale_bar_mm = 10.0
    elif option == "--scale-bar-mm":
        args.scale_bar_px = 10.0
    with pytest.raises(ValueError):
        resolve_scale(args, SimpleNamespace(top_y_px=0.0, bottom_y_px=10.0))


def test_scale_points_rejects_infinite_calculated_distance():
    """Finite coordinates that overflow their difference must be rejected."""
    args = SimpleNamespace(
        scale_mm_per_px=None,
        scale_points=(1e308, 0.0, -1e308, 0.0),
        scale_bar_px=None,
        scale_bar_mm=10.0,
        vessel_height_mm=None,
    )
    with pytest.raises(ValueError, match="距離"):
        resolve_scale(args, SimpleNamespace(top_y_px=0.0, bottom_y_px=10.0))


def test_scale_bar_mm_is_rejected_without_a_matching_pixel_measurement():
    """A known length must not be silently ignored beside another scale mode."""
    args = SimpleNamespace(
        scale_mm_per_px=0.5,
        scale_points=None,
        scale_bar_px=None,
        scale_bar_mm=50.0,
        vessel_height_mm=None,
    )
    with pytest.raises(ValueError, match="--scale-bar-px または --scale-points"):
        resolve_scale(args, SimpleNamespace(top_y_px=0.0, bottom_y_px=10.0))


@pytest.mark.parametrize("window", [-3, 2, 4])
def test_smooth_window_rejects_negative_or_even_values(window):
    """The smoothing window must follow the documented odd-or-zero rule."""
    with pytest.raises(SystemExit) as exc_info:
        main(["unused.png", "--smooth-window", str(window)])
    assert exc_info.value.code == 2


def test_filled_mode_does_not_fall_back_to_line_mode():
    """An explicit filled mode must fail when no enclosed section exists."""
    image = cylinder_shell()
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary, _ = binarize_image(gray)
    binary[45, 234:244] = 0
    with pytest.raises(ValueError, match="filled"):
        extract_section(binary, 180, profile_mode="filled")


@pytest.mark.parametrize("liquid_level_y", [math.nan, math.inf, -math.inf])
def test_liquid_level_rejects_non_finite_values(liquid_level_y):
    """Liquid level must be finite before range clipping is applied."""
    image = cylinder_shell()
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary, _ = binarize_image(gray)
    section = extract_section(binary, 180)
    with pytest.raises(ValueError, match="液面 y"):
        extract_profiles(section, 180, liquid_level_y=liquid_level_y)


def test_read_and_write_image_unicode_path(tmp_path: Path):
    """Writing and reading images using non-ASCII paths must succeed on Windows."""
    japanese_dir = tmp_path / "土器実測図_テスト出力"
    japanese_dir.mkdir()
    target_file = japanese_dir / "実測図_サンプル.png"

    sample = np.full((30, 40, 3), 200, dtype=np.uint8)
    sample[5:15, 5:15] = [0, 0, 255]
    write_image(target_file, sample)
    assert target_file.is_file()

    loaded = read_image(target_file)
    assert loaded.shape == (30, 40, 3)
    np.testing.assert_array_equal(loaded, sample)


def test_build_tsv_row_and_table_for_excel():
    mock_info = {
        "image_name": "pottery_01.png",
        "result": {
            "units": {"length": "mm", "volume": "cm³"},
            "vessel_height": 120.5,
            "mouth_diameter": 95.2,
            "maximum_diameter": 110.8,
            "capacity_ml": 450.25,
            "capacity_cm3": 450.25,
            "wall_volume_ml": 85.12,
            "wall_volume_cm3": 85.12,
            "pappus_wall_volume_ml": 84.95,
            "pappus_difference_percent": 0.20,
            "scale_mm_per_px": 0.25,
        },
    }

    # データ行のみ
    row_only = build_tsv_row(mock_info, include_header=False)
    cols = row_only.split("\t")
    assert cols[0] == "pottery_01.png"
    assert cols[1] == "120.50"
    assert cols[2] == "95.20"
    assert cols[3] == "110.80"
    assert cols[4] == "450.25"
    assert cols[5] == "85.12"
    assert cols[6] == "535.37"  # 全外形体積
    assert cols[7] == "84.95"
    assert cols[8] == "0.20"
    assert cols[9] == "0.2500"

    # ヘッダー付き
    with_header = build_tsv_row(mock_info, include_header=True)
    lines = with_header.split("\n")
    assert len(lines) == 2
    assert "画像ファイル\t器高(mm)" in lines[0]
    assert lines[1] == row_only

    # 縦の表
    table = build_tsv_table(mock_info)
    table_lines = table.split("\n")
    assert table_lines[0] == "項目\t値\t単位"
    assert "画像ファイル\tpottery_01.png" in table_lines[1]
    assert any("器高\t120.50\tmm" in line for line in table_lines)
    assert any("内腔容量\t450.25\tmL" in line for line in table_lines)
    assert any("全外形体積\t535.37\tmL" in line for line in table_lines)

