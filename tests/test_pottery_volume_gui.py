"""GUI startup logging and exception-hook tests."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from doki.gui.app import _configure_logging, _install_gui_exception_hook


def test_unhandled_exception_is_logged_and_shown(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    root_logger = logging.getLogger()
    original_level = root_logger.level
    log_path = _configure_logging()
    assert log_path == tmp_path / "PotteryVolume" / "logs" / "pottery_volume.log"

    file_handler = next(
        handler
        for handler in root_logger.handlers
        if getattr(handler, "_pottery_volume_log", False)
    )
    original_hook = sys.excepthook

    class MessageBoxStub:
        messages: list[tuple[str, str]] = []

        @classmethod
        def critical(
            cls,
            _parent: object,
            title: str,
            message: str,
        ) -> None:
            cls.messages.append((title, message))

    try:
        _install_gui_exception_hook(MessageBoxStub, log_path)
        try:
            raise RuntimeError("unexpected failure")
        except RuntimeError as exception:
            sys.excepthook(type(exception), exception, exception.__traceback__)

        assert MessageBoxStub.messages == [
            (
                "予期しないエラー",
                f"予期しないエラーが発生しました。\nunexpected failure\n\nログ: {log_path}",
            )
        ]
        file_handler.flush()
        contents = log_path.read_text(encoding="utf-8")
        assert "Unhandled GUI exception" in contents
        assert "RuntimeError: unexpected failure" in contents
    finally:
        sys.excepthook = original_hook
        root_logger.removeHandler(file_handler)
        file_handler.close()
        root_logger.setLevel(original_level)
