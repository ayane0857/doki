"""GUI integration behavior for update checks and installer launch safety."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pottery_volume_gui_window as window_module
import pottery_volume_gui_workers as workers_module
from pottery_volume_gui_window import MainWindow
from pottery_volume_gui_workers import SetupDownloadWorker, UpdateCheckWorker
from pottery_volume_updater import UpdateError


@pytest.fixture
def qt_widget(qt_app: QApplication) -> Iterator[Callable[[QWidget], None]]:
    widgets: list[QWidget] = []
    yield widgets.append
    for widget in reversed(widgets):
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(widget, QEvent.Type.DeferredDelete)
    qt_app.processEvents()


class MemorySettings:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        self.values = values or {}

    def value(self, key: str, default: object = None, *, type=None):
        value = self.values.get(key, default)
        if type is bool:
            return bool(value)
        if type is str:
            return str(value)
        return value

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = value


class UpdateMessageBoxStub:
    class Icon:
        Information = object()

    class ButtonRole:
        AcceptRole = object()
        RejectRole = object()
        DestructiveRole = object()

    selected_button = "update"

    def __init__(self, *_args) -> None:
        self.buttons: list[tuple[str, object]] = []
        self._clicked = None

    def setIcon(self, _icon) -> None:
        pass

    def setWindowTitle(self, _title: str) -> None:
        pass

    def setText(self, _text: str) -> None:
        pass

    def addButton(self, label: str, role: object) -> object:
        button = object()
        self.buttons.append((label, button))
        return button

    def setDefaultButton(self, _button: object) -> None:
        pass

    def exec(self) -> None:
        index = {"update": 0, "later": 1, "skip": 2}[self.selected_button]
        self._clicked = self.buttons[index][1]

    def clickedButton(self) -> object:
        return self._clicked


def test_update_menu_defaults_to_automatic_checks_and_has_manual_action(
    monkeypatch, qt_widget
):
    monkeypatch.setattr(window_module, "QSettings", lambda: MemorySettings())
    window = MainWindow(None)
    qt_widget(window)

    assert window.automatic_updates_action.isChecked()
    assert window.check_updates_action.text() == "更新を確認…"
    assert window.automatic_updates_action.text() == "起動時に更新を確認する"


def test_skipped_release_is_not_shown_automatically(monkeypatch, qt_widget):
    latest = "b" * 40
    window = MainWindow(None, build_version="0.1.0", build_commit="a" * 40)
    qt_widget(window)
    window._settings = MemorySettings({"skipped_update_commit": latest})
    shown: list[str] = []
    monkeypatch.setattr(window, "_show_update_available", shown.append)

    window._update_check_finished(latest)

    assert shown == []


def test_manual_check_can_show_a_previously_skipped_release(monkeypatch, qt_widget):
    latest = "b" * 40
    window = MainWindow(None, build_version="0.1.0", build_commit="a" * 40)
    qt_widget(window)
    window._settings = MemorySettings({"skipped_update_commit": latest})
    shown: list[str] = []
    monkeypatch.setattr(window, "_show_update_available", shown.append)
    window._update_check_manual = True

    window._update_check_finished(latest)

    assert shown == [latest]


def test_update_notification_actions_start_or_skip_release(monkeypatch, qt_widget):
    latest = "c" * 40
    window = MainWindow(None, build_version="0.1.0", build_commit="a" * 40)
    qt_widget(window)
    settings = MemorySettings()
    window._settings = settings
    monkeypatch.setattr(window_module, "QMessageBox", UpdateMessageBoxStub)
    started: list[str] = []
    monkeypatch.setattr(window, "_download_update_setup", started.append)

    UpdateMessageBoxStub.selected_button = "update"
    window._show_update_available(latest)
    assert started == [latest]

    UpdateMessageBoxStub.selected_button = "skip"
    window._show_update_available(latest)
    assert settings.values["skipped_update_commit"] == latest


def test_update_check_worker_logs_network_error_without_raising(caplog, monkeypatch):
    def fail():
        raise OSError("offline")

    monkeypatch.setattr(workers_module, "resolve_latest_release", fail)
    failures: list[str] = []
    worker = UpdateCheckWorker()
    worker.failed.connect(failures.append)

    with caplog.at_level(logging.INFO, logger="pottery_volume_gui_workers"):
        worker.run()

    assert failures == ["offline"]
    assert any(record.exc_info for record in caplog.records)


def test_automatic_network_failure_does_not_show_a_dialog(monkeypatch, qt_widget):
    window = MainWindow(None, build_version="0.1.0", build_commit="a" * 40)
    qt_widget(window)
    window._update_check_manual = False
    warnings: list[tuple[object, ...]] = []
    monkeypatch.setattr(window_module.QMessageBox, "warning", lambda *args: warnings.append(args))

    window._update_check_failed("offline")

    assert warnings == []


def test_manual_current_version_is_reported(monkeypatch, qt_widget):
    window = MainWindow(None, build_version="0.1.0", build_commit="a" * 40)
    qt_widget(window)
    window._update_check_manual = True
    information: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        window_module.QMessageBox, "information", lambda *args: information.append(args)
    )

    window._update_check_finished("a" * 40)

    assert information
    assert "最新" in str(information[0])


def test_hash_failure_never_emits_verified_setup_or_launches_it(
    monkeypatch, tmp_path: Path, qt_widget
):
    window = MainWindow(None, build_version="0.1.0", build_commit="a" * 40)
    qt_widget(window)
    worker = SetupDownloadWorker("b" * 40, tmp_path / "PotteryVolume-Setup.exe")
    launched: list[tuple[object, ...]] = []
    warnings: list[tuple[object, ...]] = []
    completed: list[Path] = []

    def fail_checksum(*_args, **_kwargs):
        raise UpdateError("Setup.exe の SHA-256 が一致しません。")

    monkeypatch.setattr(workers_module, "download_setup", fail_checksum)
    monkeypatch.setattr(window_module.subprocess, "Popen", lambda *args, **kwargs: launched.append(args))
    monkeypatch.setattr(window_module.QMessageBox, "warning", lambda *args: warnings.append(args))
    worker.finished.connect(completed.append)
    worker.finished.connect(window._update_download_finished)
    worker.failed.connect(window._update_download_failed)

    worker.run()

    assert completed == []
    assert launched == []
    assert warnings


def test_verified_setup_launches_detached_and_closes_the_gui(
    monkeypatch, tmp_path: Path, qt_widget
):
    monkeypatch.setattr(window_module.sys, "platform", "win32")
    window = MainWindow(None, build_version="0.1.0", build_commit="a" * 40)
    qt_widget(window)
    installer_path = tmp_path / "PotteryVolume-Setup.exe"
    command: list[list[str]] = []
    launch_options: list[dict[str, object]] = []
    quit_calls: list[bool] = []

    def fake_popen(args, **kwargs):
        command.append(args)
        launch_options.append(kwargs)

    monkeypatch.setattr(window_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        window_module.QApplication, "quit", lambda: quit_calls.append(True)
    )

    window._update_download_finished(installer_path)

    assert command == [
        [
            str(installer_path),
            "/SILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CLOSEAPPLICATIONS",
            "/UPDATE=1",
        ]
    ]
    assert launch_options[0]["cwd"] == str(tmp_path)
    assert launch_options[0]["creationflags"] & 0x8
    assert launch_options[0]["creationflags"] & 0x200
    assert quit_calls == [True]


def test_cancelled_close_does_not_start_verified_setup(
    monkeypatch, tmp_path: Path, qt_widget
):
    monkeypatch.setattr(window_module.sys, "platform", "win32")
    window = MainWindow(None, build_version="0.1.0", build_commit="a" * 40)
    qt_widget(window)
    installer_directory = tmp_path / "pending"
    installer_directory.mkdir()
    installer_path = installer_directory / "PotteryVolume-Setup.exe"
    installer_path.write_bytes(b"verified")
    window._pending_installer_directory = installer_directory
    launched: list[tuple[object, ...]] = []
    monkeypatch.setattr(window, "close", lambda: False)
    monkeypatch.setattr(
        window_module.subprocess,
        "Popen",
        lambda *args, **kwargs: launched.append((args, kwargs)),
    )

    window._update_download_finished(installer_path)

    assert launched == []
    assert not installer_directory.exists()


def test_installer_replaces_payload_only_in_post_install_and_guards_relaunch():
    installer = Path(__file__).parents[1] / "installer" / "PotteryVolume.iss"
    source = installer.read_text(encoding="utf-8")

    assert "if CurStep = ssPostInstall then begin" in source
    assert "if CurStep = ssInstall then begin" not in source
    assert "PayloadReplaced := False;" in source
    assert "PayloadReplaced := True;" in source
    assert "(CurStep = ssDone) and IsUpdateMode and PayloadReplaced" in source


def test_source_execution_skips_startup_update_check(monkeypatch, qt_widget):
    monkeypatch.setattr(window_module.sys, "platform", "win32")
    window = MainWindow(None)
    qt_widget(window)
    started: list[bool] = []
    monkeypatch.setattr(window, "_start_update_check", lambda *, manual: started.append(manual))

    window.check_updates_on_startup()

    assert started == []


def test_update_checks_and_downloads_are_windows_only(
    monkeypatch, tmp_path: Path, qt_widget
):
    monkeypatch.setattr(window_module.sys, "platform", "linux")
    window = MainWindow(None, build_version="0.1.0", build_commit="a" * 40)
    qt_widget(window)
    started: list[bool] = []
    launched: list[tuple[object, ...]] = []
    monkeypatch.setattr(window, "_start_update_check", lambda *, manual: started.append(manual))
    monkeypatch.setattr(
        window_module.subprocess, "Popen", lambda *args, **kwargs: launched.append(args)
    )

    window.check_updates_on_startup()
    window.check_for_updates_manually()
    window._download_update_setup("b" * 40)
    window._update_download_finished(tmp_path / "PotteryVolume-Setup.exe")

    assert started == []
    assert launched == []
    assert window.update_download_thread is None


def test_verified_setup_waits_until_download_thread_finishes(
    monkeypatch, tmp_path: Path, qt_widget
):
    window = MainWindow(None)
    qt_widget(window)
    installer_path = tmp_path / "PotteryVolume-Setup.exe"
    completed: list[Path] = []

    class DownloadThreadStub:
        running = True

        def isRunning(self) -> bool:
            return self.running

    thread = DownloadThreadStub()
    window.update_download_thread = thread  # type: ignore[assignment]
    monkeypatch.setattr(window, "_update_download_finished", completed.append)

    window._update_download_ready(installer_path)

    assert completed == []
    assert window._pending_setup_installer_path == installer_path

    thread.running = False
    window._finish_update_download_thread()

    assert completed == [installer_path]
    assert window._pending_setup_installer_path is None
    assert window.update_download_thread is None
