"""Command-line interface for pottery volume estimation."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import cv2

from doki.analysis.core import (
    Profiles,
    SectionResult,
    VolumeResult,
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
from doki.analysis.pipeline import (
    AnalysisOutput,
    AnalysisParams,
    AnalysisResult,
    analyze_detailed,
    resolve_scale,
)

__all__ = [
    "AnalysisOutput",
    "AnalysisParams",
    "AnalysisResult",
    "Profiles",
    "SectionResult",
    "VolumeResult",
    "analyze",
    "analyze_detailed",
    "binarize_image",
    "build_parser",
    "compute_volumes",
    "detect_axis",
    "extract_profiles",
    "extract_section",
    "main",
    "params_from_namespace",
    "parse_crop",
    "parse_points",
    "read_image",
    "remove_small_components",
    "resolve_scale",
    "visualize",
]


def params_from_namespace(args: argparse.Namespace) -> AnalysisParams:
    """Convert CLI options to the independent analysis parameter object."""
    return AnalysisParams(
        input_path=Path(args.input),
        scale_mm_per_px=args.scale_mm_per_px,
        scale_bar_px=args.scale_bar_px,
        scale_bar_mm=args.scale_bar_mm,
        scale_points=args.scale_points,
        vessel_height_mm=args.vessel_height_mm,
        axis_x=args.axis_x,
        crop=args.crop,
        liquid_level_y=args.liquid_level_y,
        closing_kernel=args.closing_kernel,
        profile_mode=args.profile_mode,
        min_component_area=args.min_component_area,
        smooth_window=args.smooth_window,
        adaptive_threshold=args.adaptive_threshold,
        debug_dir=args.debug_dir,
        json_out=args.json_out,
    )


def build_parser(
    parser_class: type[argparse.ArgumentParser] = argparse.ArgumentParser,
) -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = parser_class(
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
        help="JSON 出力先。省略時はJSONを保存しません",
    )
    return parser


def _print_result(
    result: Mapping[str, Any], section_mode: str, warnings: list[str]
) -> None:
    """Print a compact human-readable summary."""
    unit = result["units"]["length"]
    volume_unit = result["units"]["volume"]
    print("=== 土器体積推定 ===")
    print(f"器高: {result['vessel_height']:.2f} {unit}")
    print(f"口径: {result['mouth_diameter']:.2f} {unit}")
    print(f"最大径: {result['maximum_diameter']:.2f} {unit}")
    if "capacity_ml" in result:
        print(
            f"容量: {result['capacity_cm3']:.2f} cm³ ({result['capacity_ml']:.2f} mL)"
        )
        print(
            f"器壁体積: {result['wall_volume_cm3']:.2f} cm³ ({result['wall_volume_ml']:.2f} mL)"
        )
        print(
            f"パップス検算: {result['pappus_wall_volume_cm3']:.2f} cm³ ({result['pappus_wall_volume_ml']:.2f} mL) (差 {result['pappus_difference_percent']:.2f}%)"
        )
    else:
        print(f"容量: {result['capacity']:.2f} {volume_unit}")
        print(f"器壁体積: {result['wall_volume']:.2f} {volume_unit}")
        print(
            f"パップス検算: {result['pappus_wall_volume']:.2f} {volume_unit} (差 {result['pappus_difference_percent']:.2f}%)"
        )
    print(f"断面抽出モード: {section_mode}")
    for warning in warnings:
        print(f"警告: {warning}", file=sys.stderr)


def _configure_console_output() -> None:
    """Keep unsupported characters from aborting output on legacy Windows code pages."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(errors="backslashreplace")


def analyze(
    argv: list[str] | None = None,
) -> tuple[argparse.Namespace, AnalysisResult, str, list[str]]:
    """Analyze an image and return the parsed options, result, and warnings."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.closing_kernel < 1 or args.min_component_area < 1:
        parser.error("カーネルと最小連結成分面積は 1 以上で指定してください")
    if args.smooth_window < 0 or (
        args.smooth_window != 0 and args.smooth_window % 2 == 0
    ):
        parser.error("--smooth-window は奇数か 0 で指定してください")
    params = params_from_namespace(args)
    output = analyze_detailed(params)
    return args, output.result, output.section_mode, output.warnings


def main(argv: list[str] | None = None) -> int:
    """Run the image-to-volume CLI."""
    _configure_console_output()
    try:
        args, result, section_mode, all_warnings = analyze(argv)
        _print_result(result, section_mode, all_warnings)
        if args.json_out:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"JSON: {args.json_out}")
        if args.debug_dir:
            print(f"デバッグ画像: {args.debug_dir}")
        return 0
    except (ValueError, OSError, cv2.error) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
