"""Estimate a rotational pottery vessel's capacity and wall volume from a drawing.

This module preserves the historical import path while the implementation is split
into core analysis, CLI, and GUI modules.
"""

from __future__ import annotations

from pottery_volume_core import *  # noqa: F401,F403
from pottery_volume_cli import (
    _print_result,
    build_parser,
    main,
    resolve_scale,
)
from pottery_volume_gui import launch_gui


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 1:
        launch_gui()
    else:
        raise SystemExit(main())
