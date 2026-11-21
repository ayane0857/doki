"""Estimate a rotational pottery vessel's capacity and wall volume from a drawing.

This module preserves the historical import path while the implementation is split
into core analysis, CLI, and GUI modules.
"""

from __future__ import annotations

from pathlib import Path

from pottery_volume_cli import (
    AnalysisOutput,
    AnalysisParams,
    AnalysisResult,
    _print_result,  # noqa: F401  # Legacy direct import; excluded from __all__.
    analyze,
    analyze_detailed,
    build_parser,
    main,
    params_from_namespace,
    resolve_scale,
)
from pottery_volume_core import (
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


def launch_gui(initial_image: str | Path | None = None) -> int:
    """Load the desktop UI only when it is explicitly requested."""
    from pottery_volume_gui import launch_gui as _launch_gui

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


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 1:
        sys.exit(launch_gui())
    else:
        raise SystemExit(main())
