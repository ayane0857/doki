"""Run structured image analysis independently of command-line parsing."""

from __future__ import annotations

import argparse
import math
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import cv2
import numpy as np

from doki.analysis.image import (
    SectionResult,
    binarize_image,
    detect_axis,
    extract_section,
    read_image,
    remove_small_components,
)
from doki.analysis.integration import VolumeResult, compute_volumes
from doki.analysis.profiles import Profiles, extract_profiles
from doki.analysis.visualization import visualize


class AnalysisResult(VolumeResult):
    """Core volume values plus image-detection metadata written to JSON."""

    input: str
    axis_x_px: float
    section_roi: list[int]
    section_mode: str
    threshold_method: str
    top_y_px: float
    bottom_y_px: float
    warnings: list[str]


@dataclass(frozen=True)
class AnalysisParams:
    """Inputs to an image analysis, independent of command-line parsing."""

    input_path: Path
    scale_mm_per_px: float | None = None
    scale_bar_px: float | None = None
    scale_bar_mm: float | None = None
    scale_points: tuple[float, float, float, float] | None = None
    vessel_height_mm: float | None = None
    axis_x: float | None = None
    crop: tuple[int, int, int, int] | None = None
    liquid_level_y: float | None = None
    closing_kernel: int = 3
    profile_mode: str = "auto"
    min_component_area: int = 5
    smooth_window: int = 5
    adaptive_threshold: bool = False
    debug_dir: Path | None = None
    json_out: Path | None = None


@dataclass
class AnalysisOutput:
    """Full analysis state used by the GUI for manual profile corrections."""

    params: AnalysisParams
    result: AnalysisResult
    section_mode: str
    warnings: list[str]
    image: np.ndarray
    section: SectionResult
    profiles: Profiles
    mm_per_px: float | None

    @property
    def args(self) -> argparse.Namespace:
        """Legacy argparse-shaped view retained for existing callers.

        .. deprecated::
            Use ``params`` directly instead. This property will be removed in a
            future release.
        """
        warnings.warn(
            "AnalysisOutput.args は非推奨です。params を直接使用してください。",
            DeprecationWarning,
            stacklevel=2,
        )
        return argparse.Namespace(**_namespace_values(self.params))


def _namespace_values(params: AnalysisParams) -> dict[str, object]:
    """Return the historical argparse attribute names for compatibility."""
    return {
        "input": params.input_path,
        "scale_mm_per_px": params.scale_mm_per_px,
        "scale_bar_px": params.scale_bar_px,
        "scale_bar_mm": params.scale_bar_mm,
        "scale_points": params.scale_points,
        "vessel_height_mm": params.vessel_height_mm,
        "axis_x": params.axis_x,
        "crop": params.crop,
        "liquid_level_y": params.liquid_level_y,
        "closing_kernel": params.closing_kernel,
        "profile_mode": params.profile_mode,
        "min_component_area": params.min_component_area,
        "smooth_window": params.smooth_window,
        "adaptive_threshold": params.adaptive_threshold,
        "debug_dir": params.debug_dir,
        "json_out": params.json_out,
    }


def _positive_finite(value: float, message: str) -> float:
    """Validate a positive finite length, distance, or scale value."""
    if not math.isfinite(value) or value <= 0:
        raise ValueError(message)
    return float(value)


def _legacy_params(args: argparse.Namespace) -> AnalysisParams:
    """Adapt namespace-like values passed to the former public scale helper."""
    return AnalysisParams(
        input_path=Path(getattr(args, "input", "")),
        scale_mm_per_px=getattr(args, "scale_mm_per_px", None),
        scale_bar_px=getattr(args, "scale_bar_px", None),
        scale_bar_mm=getattr(args, "scale_bar_mm", None),
        scale_points=getattr(args, "scale_points", None),
        vessel_height_mm=getattr(args, "vessel_height_mm", None),
    )


def resolve_scale(
    params: AnalysisParams | argparse.Namespace, profiles: Profiles
) -> float | None:
    """Resolve one of direct, known-distance, or known-height scale inputs."""
    # Namespace support is retained for callers of the previous helper API.
    if not isinstance(params, AnalysisParams):
        params = _legacy_params(params)

    if (
        params.scale_bar_mm is not None
        and params.scale_points is None
        and params.scale_bar_px is None
    ):
        raise ValueError(
            "--scale-bar-mm は --scale-bar-px または --scale-points と一緒に指定してください"
        )

    choices = [
        params.scale_mm_per_px is not None,
        params.scale_points is not None,
        params.scale_bar_px is not None,
        params.vessel_height_mm is not None,
    ]
    if sum(choices) > 1:
        raise ValueError(
            "スケール指定は --scale-mm-per-px / --scale-points / --scale-bar-px / --vessel-height-mm のいずれか1つです"
        )
    if params.scale_mm_per_px is not None:
        return _positive_finite(
            params.scale_mm_per_px, "--scale-mm-per-px は正の値で指定してください"
        )
    if params.scale_points is not None:
        if (
            params.scale_bar_mm is None
            or not math.isfinite(params.scale_bar_mm)
            or params.scale_bar_mm <= 0
        ):
            raise ValueError(
                "--scale-points を使う場合は正の --scale-bar-mm が必要です"
            )
        x0, y0, x1, y1 = params.scale_points
        if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
            raise ValueError("--scale-points は有限な数値で指定してください")
        distance = math.hypot(x1 - x0, y1 - y0)
        if not math.isfinite(distance) or distance <= 0:
            raise ValueError("--scale-points の2点間距離は有限で正の値で指定してください")
        return _positive_finite(
            params.scale_bar_mm / distance,
            "--scale-points から計算したスケールが正しい範囲ではありません",
        )
    if params.scale_bar_px is not None:
        if (
            params.scale_bar_mm is None
            or not math.isfinite(params.scale_bar_mm)
            or params.scale_bar_mm <= 0
            or not math.isfinite(params.scale_bar_px)
            or params.scale_bar_px <= 0
        ):
            raise ValueError(
                "--scale-bar-px と --scale-bar-mm は正の値で両方指定してください"
            )
        return _positive_finite(
            params.scale_bar_mm / params.scale_bar_px,
            "スケール線から計算したスケールが正しい範囲ではありません",
        )
    if params.vessel_height_mm is not None:
        measured_height_px = profiles.bottom_y_px - profiles.top_y_px
        if (
            not math.isfinite(params.vessel_height_mm)
            or params.vessel_height_mm <= 0
            or measured_height_px <= 0
        ):
            raise ValueError("器高は正の値で指定してください")
        return _positive_finite(
            params.vessel_height_mm / measured_height_px,
            "器高から計算したスケールが正しい範囲ではありません",
        )
    return None


def analyze_detailed(params: AnalysisParams) -> AnalysisOutput:
    """Analyze an image from structured inputs and retain its editable state."""
    if params.closing_kernel < 1 or params.min_component_area < 1:
        raise ValueError("カーネルと最小連結成分面積は 1 以上で指定してください")
    if params.smooth_window < 0 or (
        params.smooth_window != 0 and params.smooth_window % 2 == 0
    ):
        raise ValueError("--smooth-window は奇数か 0 で指定してください")
    if params.profile_mode not in {"auto", "filled", "lines"}:
        raise ValueError("断面モードは auto、filled、lines のいずれかで指定してください")
    image = read_image(params.input_path)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary, threshold_method = binarize_image(gray, params.adaptive_threshold)
    binary = remove_small_components(binary, params.min_component_area)
    axis_x, warnings = detect_axis(binary, params.axis_x)
    section = extract_section(
        binary, axis_x, params.crop, params.closing_kernel, params.profile_mode
    )
    if section.mode == "lines":
        section.contour_mask = section.mask.copy()
    profiles = extract_profiles(
        section, axis_x, params.liquid_level_y, params.smooth_window
    )
    scale = resolve_scale(params, profiles)
    all_warnings = warnings + section.warnings
    if scale is None:
        all_warnings.append(
            "スケール未指定のため、体積は px³ 単位です。実寸換算にはスケールを指定してください。"
        )
    result = cast(
        AnalysisResult,
        compute_volumes(profiles, section.mask, axis_x, scale, section.mode),
    )
    result.update(
        {
            "input": str(params.input_path),
            "axis_x_px": axis_x,
            "section_roi": list(section.roi),
            "section_mode": section.mode,
            "threshold_method": threshold_method,
            "top_y_px": profiles.top_y_px,
            "bottom_y_px": profiles.bottom_y_px,
            "warnings": all_warnings,
        }
    )
    if params.debug_dir:
        visualize(image, axis_x, section, profiles, scale, params.debug_dir)
    return AnalysisOutput(
        params, result, section.mode, all_warnings, image, section, profiles, scale
    )
