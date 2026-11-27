"""Public API for pottery volume estimation."""

from __future__ import annotations

from pathlib import Path

from doki.analysis.core import (
    Profiles,
    SectionResult,
    VolumeResult,
    apply_profile_overrides,
    binarize_image,
    compute_volumes,
    detect_axis,
    extract_profiles,
    extract_section,
    parse_crop,
    parse_points,
    profile_section_polygon,
    read_image,
    remove_small_components,
    visualize,
    write_image,
)
from doki.cli import (
    AnalysisOutput,
    AnalysisParams,
    AnalysisResult,
    _print_result,  # noqa: F401  # Private convenience import.
    analyze,
    analyze_detailed,
    build_parser,
    main,
    params_from_namespace,
    resolve_scale,
)


def launch_gui(initial_image: str | Path | None = None) -> int:
    """Load the desktop UI only when it is explicitly requested."""
    from doki.gui.app import launch_gui as _launch_gui

    return _launch_gui(initial_image)


__all__ = [
    "AnalysisOutput",
    "AnalysisParams",
    "AnalysisResult",
    "Profiles",
    "SectionResult",
    "VolumeResult",
    "analyze",
    "analyze_detailed",
    "apply_profile_overrides",
    "binarize_image",
    "build_parser",
    "compute_volumes",
    "detect_axis",
    "extract_profiles",
    "extract_section",
    "launch_gui",
    "main",
    "params_from_namespace",
    "parse_crop",
    "parse_points",
    "profile_section_polygon",
    "read_image",
    "remove_small_components",
    "resolve_scale",
    "visualize",
    "write_image",
]
