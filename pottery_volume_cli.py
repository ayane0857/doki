"""Command-line interface for pottery volume estimation."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import cv2

from pottery_volume_core import (
    Profiles,
    binarize_image,
    compute_volumes,
    detect_axis,
    extract_profiles,
    extract_section,
    parse_crop,
    parse_points,
    read_image,
    remove_small_components,
    visualize,
)

def resolve_scale(args: argparse.Namespace, profiles: Profiles) -> float | None:
    """Resolve one of direct, known-distance, or known-height scale inputs."""
    def validate_scale(value: float, message: str) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError(message)
        return float(value)

    if (
        args.scale_bar_mm is not None
        and args.scale_points is None
        and args.scale_bar_px is None
    ):
        raise ValueError(
            "--scale-bar-mm は --scale-bar-px または --scale-points と一緒に指定してください"
        )

    choices = [
        args.scale_mm_per_px is not None,
        args.scale_points is not None,
        args.scale_bar_px is not None,
        args.vessel_height_mm is not None,
    ]
    if sum(choices) > 1:
        raise ValueError(
            "スケール指定は --scale-mm-per-px / --scale-points / --scale-bar-px / --vessel-height-mm のいずれか1つです"
        )
    if args.scale_mm_per_px is not None:
        if not math.isfinite(args.scale_mm_per_px) or args.scale_mm_per_px <= 0:
            raise ValueError("--scale-mm-per-px は正の値で指定してください")
        return validate_scale(args.scale_mm_per_px, "--scale-mm-per-px は正の値で指定してください")
    if args.scale_points is not None:
        if (
            args.scale_bar_mm is None
            or not math.isfinite(args.scale_bar_mm)
            or args.scale_bar_mm <= 0
        ):
            raise ValueError(
                "--scale-points を使う場合は正の --scale-bar-mm が必要です"
            )
        x0, y0, x1, y1 = args.scale_points
        if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
            raise ValueError("--scale-points は有限な数値で指定してください")
        distance = math.hypot(x1 - x0, y1 - y0)
        if not math.isfinite(distance) or distance <= 0:
            raise ValueError("--scale-points の2点間距離は有限で正の値で指定してください")
        return validate_scale(
            args.scale_bar_mm / distance,
            "--scale-points から計算したスケールが正しい範囲ではありません",
        )
    if args.scale_bar_px is not None:
        if (
            args.scale_bar_mm is None
            or not math.isfinite(args.scale_bar_mm)
            or args.scale_bar_mm <= 0
            or not math.isfinite(args.scale_bar_px)
            or args.scale_bar_px <= 0
        ):
            raise ValueError(
                "--scale-bar-px と --scale-bar-mm は正の値で両方指定してください"
            )
        return validate_scale(
            args.scale_bar_mm / args.scale_bar_px,
            "スケール線から計算したスケールが正しい範囲ではありません",
        )
    if args.vessel_height_mm is not None:
        measured_height_px = profiles.bottom_y_px - profiles.top_y_px
        if (
            not math.isfinite(args.vessel_height_mm)
            or args.vessel_height_mm <= 0
            or measured_height_px <= 0
        ):
            raise ValueError("器高は正の値で指定してください")
        return validate_scale(
            args.vessel_height_mm / measured_height_px,
            "器高から計算したスケールが正しい範囲ではありません",
        )
    return None


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="土器実測図から回転軸対称を仮定して容量と器壁体積を推定します。"
    )
    parser.add_argument("input", type=Path, help="入力画像 (PNG/JPEGなど)")
    parser.add_argument("--scale-mm-per-px", type=float, help="直接指定する mm/px")
    parser.add_argument(
        "--scale-bar-px", type=float, help="既知スケール線の画像上の長さ (px)"
    )
    parser.add_argument("--scale-bar-mm", type=float, help="既知スケール線の実寸 (mm)")
    parser.add_argument(
        "--scale-points", type=parse_points, help="既知長の両端 x0,y0,x1,y1 (px)"
    )
    parser.add_argument(
        "--vessel-height-mm", type=float, help="器高の実寸からスケールを算出 (mm)"
    )
    parser.add_argument("--axis-x", type=float, help="回転軸 x 座標を手動指定 (px)")
    parser.add_argument("--crop", type=parse_crop, help="断面検索範囲 x0,y0,x1,y1")
    parser.add_argument(
        "--liquid-level-y", type=float, help="液面 y 座標 (px)。既定は口縁"
    )
    parser.add_argument(
        "--closing-kernel",
        type=int,
        default=3,
        help="隙間を閉じる形態学カーネルサイズ (px、既定 3)",
    )
    parser.add_argument(
        "--profile-mode",
        choices=("auto", "filled", "lines"),
        default="auto",
        help="断面抽出方式 (既定 auto)",
    )
    parser.add_argument(
        "--min-component-area",
        type=int,
        default=5,
        help="二値化後に残す最小連結成分面積 (px)",
    )
    parser.add_argument(
        "--smooth-window", type=int, default=5, help="輪郭平滑化窓 (奇数 px、0 で無効)"
    )
    parser.add_argument(
        "--adaptive-threshold", action="store_true", help="適応的二値化を強制"
    )
    parser.add_argument(
        "--debug-dir", type=Path, help="重ね合わせ画像、断面マスク、輪郭グラフの出力先"
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=Path("result.json"),
        help="JSON 出力先 (既定: ./result.json)",
    )
    return parser


def _print_result(
    result: dict[str, Any], section_mode: str, warnings: list[str]
) -> None:
    """Print a compact human-readable summary."""
    unit = result["units"]["length"]
    volume_unit = result["units"]["volume"]
    print("=== 土器体積推定 ===")
    print(f"器高: {result['vessel_height']:.2f} {unit}")
    print(f"口径: {result['mouth_diameter']:.2f} {unit}")
    print(f"最大径: {result['maximum_diameter']:.2f} {unit}")
    print(f"容量: {result['capacity']:.2f} {volume_unit}")
    print(f"器壁体積: {result['wall_volume']:.2f} {volume_unit}")
    if "capacity_ml" in result:
        print(
            f"容量: {result['capacity_cm3']:.2f} cm³ ({result['capacity_ml']:.2f} mL)"
        )
        print(
            f"器壁体積: {result['wall_volume_cm3']:.2f} cm³ ({result['wall_volume_ml']:.2f} mL)"
        )
    print(
        f"パップス検算: {result['pappus_wall_volume']:.2f} {volume_unit} (差 {result['pappus_difference_percent']:.2f}%)"
    )
    print(f"断面抽出モード: {section_mode}")
    for warning in warnings:
        print(f"警告: {warning}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Run the image-to-volume CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.closing_kernel < 1 or args.min_component_area < 1:
        parser.error("カーネルと最小連結成分面積は 1 以上で指定してください")
    if args.smooth_window < 0 or (
        args.smooth_window != 0 and args.smooth_window % 2 == 0
    ):
        parser.error("--smooth-window は奇数か 0 で指定してください")
    try:
        image = read_image(args.input)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        binary, threshold_method = binarize_image(gray, args.adaptive_threshold)
        binary = remove_small_components(binary, args.min_component_area)
        axis_x, warnings = detect_axis(binary, args.axis_x)
        section = extract_section(
            binary, axis_x, args.crop, args.closing_kernel, args.profile_mode
        )
        profiles = extract_profiles(
            section, axis_x, args.liquid_level_y, args.smooth_window
        )
        scale = resolve_scale(args, profiles)
        all_warnings = warnings + section.warnings
        if scale is None:
            all_warnings.append(
                "スケール未指定のため、体積は px³ 単位です。実寸換算にはスケールを指定してください。"
            )
        result = compute_volumes(profiles, section.mask, axis_x, scale, section.mode)
        result.update(
            {
                "input": str(args.input),
                "axis_x_px": axis_x,
                "section_roi": list(section.roi),
                "section_mode": section.mode,
                "threshold_method": threshold_method,
                "top_y_px": profiles.top_y_px,
                "bottom_y_px": profiles.bottom_y_px,
                "warnings": all_warnings,
            }
        )
        _print_result(result, section.mode, all_warnings)
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"JSON: {args.json_out}")
        if args.debug_dir:
            visualize(image, axis_x, section, profiles, scale, args.debug_dir)
            print(f"デバッグ画像: {args.debug_dir}")
        return 0
    except (ValueError, OSError, cv2.error) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2
