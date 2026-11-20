"""Application entry point and pure helper re-exports for the GUI."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Any

from pottery_volume_geometry import pixel_distance
from pottery_volume_gui_helpers import (
    GUIArgumentParser,
    Info,
    Result,
    build_tsv_row,
    build_tsv_table,
)


def _configure_logging() -> Path | None:
    """Write GUI logs to a user-writable state directory, with a temp fallback."""
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler) and getattr(
            handler, "_pottery_volume_log", False
        ):
            return Path(handler.baseFilename)

    local_app_data = os.environ.get("LOCALAPPDATA")
    state_home = os.environ.get("XDG_STATE_HOME")
    if local_app_data:
        primary_directory = Path(local_app_data) / "PotteryVolume" / "logs"
    else:
        state_directory = (
            Path(state_home) if state_home else Path.home() / ".local" / "state"
        )
        primary_directory = state_directory / "PotteryVolume" / "logs"

    directories = (
        primary_directory,
        Path(tempfile.gettempdir()) / "PotteryVolume" / "logs",
    )
    for directory in directories:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(
                directory / "pottery_volume.log", encoding="utf-8"
            )
        except OSError:
            continue
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        handler._pottery_volume_log = True  # pyright: ignore[reportAttributeAccessIssue]
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)
        return directory / "pottery_volume.log"

    logging.basicConfig(level=logging.ERROR)
    return None


def _logging_excepthook(
    exception_type: type[BaseException],
    exception: BaseException,
    traceback: TracebackType | None,
) -> None:
    if issubclass(exception_type, KeyboardInterrupt):
        sys.__excepthook__(exception_type, exception, traceback)
        return
    logging.getLogger(__name__).critical(
        "Unhandled GUI exception",
        exc_info=(exception_type, exception, traceback),
    )


def _install_gui_exception_hook(message_box: Any, log_path: Path | None) -> None:
    def handle_exception(
        exception_type: type[BaseException],
        exception: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        if issubclass(exception_type, KeyboardInterrupt):
            sys.__excepthook__(exception_type, exception, traceback)
            return
        logging.getLogger(__name__).critical(
            "Unhandled GUI exception",
            exc_info=(exception_type, exception, traceback),
        )
        summary = str(exception).strip() or exception_type.__name__
        log_note = f"\n\nログ: {log_path}" if log_path else ""
        try:
            message_box.critical(
                None,
                "予期しないエラー",
                f"予期しないエラーが発生しました。\n{summary}{log_note}",
            )
        except Exception:
            sys.__excepthook__(exception_type, exception, traceback)

    sys.excepthook = handle_exception


def launch_gui(initial_image: str | Path | None = None) -> int:
    """Import Qt and open the desktop interface on demand."""
    log_path = _configure_logging()
    sys.excepthook = _logging_excepthook

    from PySide6.QtWidgets import QApplication, QMessageBox

    instance = QApplication.instance()
    app = instance if isinstance(instance, QApplication) else QApplication(sys.argv)
    app.setApplicationName("PotteryVolume")
    app.setOrganizationName("PotteryVolume")
    _install_gui_exception_hook(QMessageBox, log_path)

    from PySide6.QtCore import QSettings

    from pottery_volume_gui_style import stylesheet_for_theme
    from pottery_volume_gui_window import MainWindow

    app.setStyle("Fusion")
    settings = QSettings()
    theme = settings.value("theme_mode", None, type=str)
    if theme not in {"system", "light", "dark"}:
        legacy_dark_mode = settings.value("dark_mode", None, type=bool)
        theme = (
            "dark"
            if legacy_dark_mode is True
            else "light"
            if settings.contains("dark_mode")
            else "system"
        )
    app.setProperty("pottery_theme_mode", theme)

    def apply_theme() -> None:
        current_theme = app.property("pottery_theme_mode") or "system"
        app.setStyleSheet(stylesheet_for_theme(current_theme, app))

    apply_theme()
    app.styleHints().colorSchemeChanged.connect(apply_theme)
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
