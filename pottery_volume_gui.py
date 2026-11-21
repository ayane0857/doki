"""Application entry point and pure helper re-exports for the GUI."""

from __future__ import annotations

import ctypes
import json
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

_APPLICATION_MUTEX_HANDLE: Any = None
_APPLICATION_MUTEX_NAME = r"Local\PotteryVolumeAppMutex"


def _retain_application_mutex() -> None:
    """Keep the named mutex that Inno Setup checks during install/uninstall."""
    global _APPLICATION_MUTEX_HANDLE
    if os.name != "nt" or _APPLICATION_MUTEX_HANDLE is not None:
        return
    try:
        loader_name = "WinDLL"
        kernel32 = getattr(ctypes, loader_name)("kernel32", use_last_error=True)
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        create_mutex.restype = ctypes.c_void_p
        handle = create_mutex(None, 0, _APPLICATION_MUTEX_NAME)
        if not handle:
            raise OSError("CreateMutexW failed")
        _APPLICATION_MUTEX_HANDLE = handle
    except Exception:
        logging.getLogger(__name__).exception(
            "アプリケーション mutex を作成できません"
        )


def _release_application_mutex() -> None:
    """Release the mutex just before this process starts its own Setup update."""
    global _APPLICATION_MUTEX_HANDLE
    if os.name != "nt" or _APPLICATION_MUTEX_HANDLE is None:
        return
    handle = _APPLICATION_MUTEX_HANDLE
    _APPLICATION_MUTEX_HANDLE = None
    try:
        loader_name = "WinDLL"
        kernel32 = getattr(ctypes, loader_name)("kernel32", use_last_error=True)
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_int
        if not close_handle(handle):
            raise OSError("CloseHandle failed")
    except Exception:
        logging.getLogger(__name__).exception(
            "アプリケーション mutex を解放できません"
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


def _read_build_info() -> tuple[str, str]:
    """Read embedded release metadata; source runs intentionally identify as dev."""
    if not getattr(sys, "frozen", False):
        return "dev", "dev"
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    try:
        info = json.loads((bundle_root / "BUILD_INFO.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        logging.getLogger(__name__).exception("Could not read BUILD_INFO.json")
        return "dev", "dev"
    version = info.get("version")
    commit = info.get("commit")
    if not isinstance(version, str) or not version:
        version = "dev"
    if not isinstance(commit, str) or not commit:
        commit = "dev"
    return version, commit


def launch_gui(initial_image: str | Path | None = None) -> int:
    """Import Qt and open the desktop interface on demand."""
    _retain_application_mutex()
    log_path = _configure_logging()
    sys.excepthook = _logging_excepthook

    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen

    instance = QApplication.instance()
    app = instance if isinstance(instance, QApplication) else QApplication(sys.argv)
    app.setApplicationName("PotteryVolume")
    app.setOrganizationName("PotteryVolume")
    _install_gui_exception_hook(QMessageBox, log_path)

    from PySide6.QtCore import QSettings, QTimer, Qt

    from pottery_volume_gui_style import stylesheet_for_theme

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

    splash_pixmap = QPixmap(520, 260)
    splash_pixmap.fill(QColor("#1f2937"))
    painter = QPainter(splash_pixmap)
    painter.setPen(QColor("#f9fafb"))
    title_font = QFont()
    title_font.setPointSize(22)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.drawText(32, 92, "PotteryVolume")
    subtitle_font = QFont()
    subtitle_font.setPointSize(11)
    painter.setFont(subtitle_font)
    painter.setPen(QColor("#d1d5db"))
    painter.drawText(34, 128, "土器体積・容量推定")
    painter.drawText(34, 204, "起動しています…")
    painter.end()
    splash = QSplashScreen(splash_pixmap)
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()

    from pottery_volume_gui_window import MainWindow

    build_version, build_commit = _read_build_info()
    window = MainWindow(
        initial_image,
        build_version=build_version,
        build_commit=build_commit,
    )
    window.show()
    splash.finish(window)
    QTimer.singleShot(0, window.check_updates_on_startup)
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
