"""Synthetic integration tests for vessel volume estimation."""

from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from pottery_volume import (
    AnalysisParams,
    analyze_detailed,
    apply_profile_overrides,
    binarize_image,
    compute_volumes,
    detect_axis,
    extract_profiles,
    extract_section,
    main,
    profile_section_polygon,
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


def test_analysis_params_preserve_baseline_numeric_results(tmp_path: Path):
    """The structured API retains the former integration's values within tight tolerance."""
    image_path = tmp_path / "cylinder.png"
    write_image(image_path, cylinder_shell())

    params = AnalysisParams(input_path=image_path, scale_mm_per_px=0.5)
    output = analyze_detailed(params)

    assert output.params is params
    assert output.params.input_path == image_path
    assert output.result["capacity"] == pytest.approx(
        183334.8931735552, rel=1e-15, abs=0.0
    )
    assert output.result["wall_volume"] == pytest.approx(
        73887.38689914855, rel=1e-15, abs=0.0
    )
    assert output.result["pappus_wall_volume"] == pytest.approx(
        73887.38689914795, rel=1e-12, abs=0.0
    )
    # The independent volume calculations should agree to near machine precision.
    assert output.result["pappus_difference_percent"] < 1e-12
    assert output.result["capacity_ml"] == pytest.approx(
        183.3348931735552, rel=1e-15, abs=0.0
    )
    assert output.result["wall_volume_ml"] == pytest.approx(
        73.88738689914855, rel=1e-15, abs=0.0
    )
    assert output.result["mm_per_px"] == 0.5
    assert "scale_mm_per_px" not in output.result


def test_resolve_scale_accepts_analysis_params():
    params = AnalysisParams(input_path=Path("input.png"), scale_mm_per_px=0.25)
    profiles = SimpleNamespace(top_y_px=0.0, bottom_y_px=10.0)

    assert resolve_scale(params, profiles) == 0.25


def test_cli_import_does_not_load_qt():
    """CLI and pure GUI helper imports do not require a Qt runtime."""
    code = (
        "import sys; import pottery_volume; import pottery_volume_gui; "
        "import pottery_volume_gui_qt; "
        "assert not any(name == 'PySide6' or name.startswith('PySide6.') "
        "for name in sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_cli_module_runs_directly():
    """The packaged CLI entry point responds to --help without launching the GUI."""
    result = subprocess.run(
        [sys.executable, "-m", "pottery_volume_cli", "--help"],
        capture_output=True,
        check=True,
    )
    assert b"usage:" in result.stdout.lower()


def test_cli_module_handles_cp932_console_output():
    image = Path(__file__).parent / "fixtures" / "pottery_image.png"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp932:strict"

    result = subprocess.run(
        [sys.executable, "-m", "pottery_volume_cli", str(image), "--scale-mm-per-px", "0.13"],
        capture_output=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr


def test_pixel_distance_returns_image_distance():
    """The GUI measurement helper reports the Euclidean pixel distance."""
    assert pixel_distance((10, 20), (13, 24)) == pytest.approx(5)


@pytest.mark.parametrize("point_b", [(math.nan, 0.0), (math.inf, 0.0), (-math.inf, 0.0)])
def test_pixel_distance_rejects_non_finite_coordinates(point_b):
    with pytest.raises(ValueError):
        pixel_distance((0.0, 0.0), point_b)


def test_print_result_remains_importable_but_private():
    import pottery_volume

    assert callable(pottery_volume._print_result)
    assert "_print_result" not in pottery_volume.__all__


def test_profile_section_polygon_is_valid_and_reports_shapely_centroid():
    """Shapely should validate the profile polygon and compute its wall centroid."""
    image = cylinder_shell()
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary, _ = binarize_image(gray)
    section = extract_section(binary, 180)
    profiles = extract_profiles(section, 180)

    polygon = profile_section_polygon(profiles, 180)
    result = compute_volumes(profiles, section.mask, 180, section_mode=section.mode)

    assert polygon.is_valid
    assert polygon.area == pytest.approx(result["section_area"], rel=0.02)
    assert result["section_centroid_radius"] == pytest.approx(
        float(polygon.centroid.x - 180), rel=0.02
    )


def test_manual_profile_overrides_recompute_wall_volume():
    """A confirmed manual profile should replace the automatic radii."""
    image = cylinder_shell()
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary, _ = binarize_image(gray)
    section = extract_section(binary, 180)
    profiles = extract_profiles(section, 180)

    inner = profiles.r_in_px.copy()
    outer = profiles.r_out_px.copy()
    inner[:] = 50.0
    outer[:] = 60.0
    manual = apply_profile_overrides(profiles, inner, outer)
    result = compute_volumes(manual, np.zeros_like(section.mask), 180)

    expected_wall = math.pi * (60.0**2 - 50.0**2) * (
        manual.bottom_y_px - manual.top_y_px
    )
    assert result["wall_volume"] == pytest.approx(expected_wall, rel=0.02)
    assert result["pappus_difference_percent"] == pytest.approx(0.0, abs=0.01)


def test_low_resolution_270_by_170_image():
    """The automatic detector should retain accuracy on a small drawing."""
    result, axis = run_pipeline(low_resolution_cylinder_shell())
    expected = math.pi * 38**2 * 105
    expected_wall = math.pi * (45**2 - 38**2) * 105
    assert axis == pytest.approx(135, abs=1)
    assert result["capacity"] == pytest.approx(expected, rel=0.05)
    assert result["wall_volume"] == pytest.approx(expected_wall, rel=0.05)
    assert result["pappus_difference_percent"] < 5


def test_pottery_fixture_bottom_profile_rejects_terminal_fragment():
    """A broken bottom-edge fragment must not pull the final inner radius outward."""
    image = read_image(Path(__file__).parent / "fixtures" / "pottery_image.png")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary, _ = binarize_image(gray)
    binary = remove_small_components(binary, min_area=2)
    axis, _ = detect_axis(binary)
    section = extract_section(binary, axis)
    profiles = extract_profiles(section, axis)

    assert profiles.bottom_y_px == 436
    assert profiles.r_in_px[-1] < 12
    assert profiles.r_out_px[-1] > 60
    assert any("器底付近" in warning for warning in profiles.warnings)


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


def test_tsv_cell_content_cannot_add_rows_or_columns():
    info = {
        "image_name": "pottery\t01\nimage.png",
        "result": {
            "units": {"length": "mm", "volume": "mm³"},
            "vessel_height": 12.0,
            "mouth_diameter": 9.0,
            "maximum_diameter": 11.0,
            "capacity_ml": 4.0,
            "capacity_cm3": 4.0,
            "wall_volume_ml": 2.0,
            "wall_volume_cm3": 2.0,
            "pappus_wall_volume_ml": 2.0,
            "pappus_difference_percent": 0.0,
            "mm_per_px": 0.25,
        },
    }

    row = build_tsv_row(info, include_header=True)
    table = build_tsv_table(info)

    assert len(row.splitlines()) == 2
    assert len(row.splitlines()[1].split("\t")) == 10
    assert row.splitlines()[1].split("\t")[0] == "pottery 01 image.png"
    assert len(table.splitlines()) == 12
    assert table.splitlines()[1].split("\t")[1] == "pottery 01 image.png"


def test_tsv_builders_keep_exact_legacy_output():
    scaled = {
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
    pixels = {
        "image_name": "vessel.png",
        "result": {
            "units": {"length": "px", "volume": "px³"},
            "vessel_height": 10.0,
            "mouth_diameter": 4.0,
            "maximum_diameter": 6.0,
            "capacity": 20.0,
            "wall_volume": 3.0,
            "pappus_wall_volume": 3.1,
            "pappus_difference_percent": 3.3,
            "mm_per_px": None,
        },
    }

    assert build_tsv_row(scaled, include_header=True) == (
        "画像ファイル\t器高(mm)\t口径(mm)\t最大径(mm)\t内腔容量(cm³)\t"
        "器壁体積(cm³)\t全外形体積(cm³)\tパップス検算(cm³)\tパップス差(%)\tmm/px\n"
        "pottery_01.png\t120.50\t95.20\t110.80\t450.25\t85.12\t535.37\t"
        "84.95\t0.20\t0.2500"
    )
    assert build_tsv_table(scaled) == (
        "項目\t値\t単位\n"
        "画像ファイル\tpottery_01.png\n"
        "器高\t120.50\tmm\n"
        "口径\t95.20\tmm\n"
        "最大径\t110.80\tmm\n"
        "内腔容量\t450.25\tmL\n"
        "内腔容量(cm³)\t450.25\tcm³\n"
        "器壁体積\t85.12\tmL\n"
        "全外形体積\t535.37\tmL\n"
        "パップス検算\t84.95\tmL\n"
        "パップス差\t0.20\t%\n"
        "スケール\t0.2500\tmm/px"
    )
    assert build_tsv_row(pixels, include_header=True) == (
        "画像ファイル\t器高(px)\t口径(px)\t最大径(px)\t内腔容量(px³)\t"
        "器壁体積(px³)\t全外形体積(px³)\tパップス検算(px³)\tパップス差(%)\n"
        "vessel.png\t10.00\t4.00\t6.00\t20.00\t3.00\t23.00\t3.10\t3.30"
    )
    assert build_tsv_table(pixels) == (
        "項目\t値\t単位\n"
        "画像ファイル\tvessel.png\n"
        "器高\t10.00\tpx\n"
        "口径\t4.00\tpx\n"
        "最大径\t6.00\tpx\n"
        "内腔容量\t20.00\tpx³\n"
        "器壁体積\t3.00\tpx³\n"
        "全外形体積\t23.00\tpx³\n"
        "パップス検算\t3.10\tpx³\n"
        "パップス差\t3.30\t%"
    )

