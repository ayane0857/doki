"""Application entry point and pure helper re-exports for the GUI."""

from __future__ import annotations

import sys
from pathlib import Path

from pottery_volume_gui_helpers import (
    GUIArgumentParser,
    Info,
    Result,
    build_tsv_row,
    build_tsv_table,
)
from pottery_volume_geometry import pixel_distance


def launch_gui(initial_image: str | Path | None = None) -> int:
    """Import Qt and open the desktop interface on demand."""
    from PySide6.QtWidgets import QApplication

    from pottery_volume_gui_style import APP_STYLESHEET
    from pottery_volume_gui_window import MainWindow

    instance = QApplication.instance()
    app = instance if isinstance(instance, QApplication) else QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)
    window = MainWindow(initial_image)
    window.show()
    return app.exec()


__all__ = [
    "GUIArgumentParser",
    "Info",
    "Result",
    "build_tsv_row",
    "build_tsv_table",
    "launch_gui",
    "pixel_distance",
]
