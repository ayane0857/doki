"""Main window update checks and installer downloads."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
    QProgressDialog,
)

from doki.gui.workers import (
    SetupDownloadWorker,
    UpdateCheckWorker,
)
from doki.updater import update_available

if TYPE_CHECKING:
    from doki.gui.window.main import MainWindow

logger = logging.getLogger(__name__)


def check_updates_on_startup(self: MainWindow) -> None:
    if sys.platform != "win32":
        return
    if self.build_commit.lower() == "dev":
        logger.debug("Source execution: automatic update checks are disabled")
        return
    if self.automatic_updates_action.isChecked():
        self._start_update_check(manual=False)


def check_for_updates_manually(self: MainWindow) -> None:
    if sys.platform != "win32":
        return
    if self.build_commit.lower() == "dev":
        QMessageBox.information(
            self,
            "更新を確認",
            "ソース実行では更新確認を利用できません。",
        )
        return
    self._start_update_check(manual=True)


def _start_update_check(self: MainWindow, *, manual: bool) -> None:
    if self.update_check_thread is not None:
        if manual:
            QMessageBox.information(self, "更新を確認", "更新を確認しています。")
        return
    self._update_check_manual = manual
    thread = QThread(self)
    worker = UpdateCheckWorker()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(self._update_check_finished)
    worker.failed.connect(self._update_check_failed)
    worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
    worker.failed.connect(thread.quit, Qt.ConnectionType.DirectConnection)
    thread.finished.connect(self._clear_update_check_worker)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    self.update_check_thread = thread
    self.update_check_worker = worker
    self.check_updates_action.setEnabled(False)
    thread.start()


def _clear_update_check_worker(self: MainWindow) -> None:
    self.update_check_thread = None
    self.update_check_worker = None
    self.check_updates_action.setEnabled(True)


def _update_check_finished(self: MainWindow, latest_commit: str) -> None:
    manual = self._update_check_manual
    if not update_available(self.build_commit, latest_commit):
        if manual:
            QMessageBox.information(
                self, "更新を確認", "PotteryVolume は最新です。"
            )
        return
    skipped = cast(str, self._settings.value("skipped_update_commit", "", type=str))
    if not manual and skipped.lower() == latest_commit.lower():
        return
    self._show_update_available(latest_commit)


def _update_check_failed(self: MainWindow, _summary: str) -> None:
    if self._update_check_manual:
        QMessageBox.warning(
            self,
            "更新を確認できません",
            "最新版を確認できませんでした。ネットワーク接続を確認してください。",
        )


def _show_update_available(self: MainWindow, latest_commit: str) -> None:
    message = QMessageBox(self)
    message.setIcon(QMessageBox.Icon.Information)
    message.setWindowTitle("更新があります")
    message.setText(
        "新しいバージョンのPotteryVolumeを利用できます。\n"
        f"現在: {self.build_version} ({self.build_commit[:12]})\n"
        f"最新版のコミット: {latest_commit[:12]}"
    )
    update_button = message.addButton(
        "今すぐ更新", QMessageBox.ButtonRole.AcceptRole
    )
    message.addButton("後で", QMessageBox.ButtonRole.RejectRole)
    skip_button = message.addButton(
        "この版をスキップ", QMessageBox.ButtonRole.DestructiveRole
    )
    message.setDefaultButton(update_button)
    message.exec()
    if message.clickedButton() is update_button:
        self._download_update_setup(latest_commit)
    elif message.clickedButton() is skip_button:
        self._settings.setValue("skipped_update_commit", latest_commit)


def _download_update_setup(self: MainWindow, commit: str) -> None:
    if sys.platform != "win32":
        return
    if self.update_download_thread is not None:
        return
    self._pending_installer_directory = Path(
        tempfile.mkdtemp(prefix="PotteryVolume-update-")
    )
    destination = self._pending_installer_directory / "PotteryVolume-Setup.exe"
    dialog = QProgressDialog(
        "更新プログラムをダウンロードしています…",
        "キャンセル",
        0,
        100,
        self,
    )
    dialog.setWindowTitle("PotteryVolumeの更新")
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setMinimumDuration(0)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    self.update_progress_dialog = dialog

    thread = QThread(self)
    worker = SetupDownloadWorker(commit, destination)
    worker.moveToThread(thread)
    dialog.canceled.connect(worker.cancel, Qt.ConnectionType.DirectConnection)
    thread.started.connect(worker.run)
    for signal in (worker.finished, worker.failed, worker.cancelled):
        signal.connect(thread.quit, Qt.ConnectionType.DirectConnection)
    worker.progress.connect(self._update_download_progress)
    worker.finished.connect(self._update_download_ready)
    worker.failed.connect(self._update_download_failed)
    worker.cancelled.connect(self._update_download_cancelled)
    thread.finished.connect(self._finish_update_download_thread)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    self.update_download_thread = thread
    self.update_download_worker = worker
    dialog.show()
    thread.start()


def _update_download_progress(self: MainWindow, received: int, total: int) -> None:
    dialog = self.update_progress_dialog
    if dialog is None:
        return
    if total > 0:
        dialog.setRange(0, 100)
        dialog.setValue(min(received * 100 // total, 100))
        dialog.setLabelText(
            f"更新プログラムをダウンロードしています… "
            f"{received // (1024 * 1024)} / {total // (1024 * 1024)} MB"
        )
    else:
        dialog.setRange(0, 0)


def _finish_update_download_dialog(self: MainWindow) -> None:
    if self.update_progress_dialog is not None:
        self.update_progress_dialog.close()
        self.update_progress_dialog.deleteLater()
        self.update_progress_dialog = None


def _clear_update_download_worker(self: MainWindow) -> None:
    self.update_download_thread = None
    self.update_download_worker = None


def _update_download_ready(self: MainWindow, installer_path: Path) -> None:
    self._pending_setup_installer_path = installer_path
    thread = self.update_download_thread
    if thread is None or not thread.isRunning():
        self._finish_update_download_thread()


def _finish_update_download_thread(self: MainWindow) -> None:
    installer_path = self._pending_setup_installer_path
    self._pending_setup_installer_path = None
    self._clear_update_download_worker()
    if installer_path is not None:
        self._update_download_finished(installer_path)


def _update_download_finished(self: MainWindow, installer_path: Path) -> None:
    if sys.platform != "win32":
        self._finish_update_download_dialog()
        self._remove_pending_installer()
        return
    self._finish_update_download_dialog()
    # close() returns False when closeEvent rejects the request (for example,
    # while image processing is active), so Setup is never started then.
    app = QApplication.instance()
    if isinstance(app, QApplication):
        app.setQuitOnLastWindowClosed(False)
    if not self.close():
        if isinstance(app, QApplication):
            app.setQuitOnLastWindowClosed(True)
        self._remove_pending_installer()
        return
    from doki.gui.app import (
        _release_application_mutex,
        _retain_application_mutex,
    )

    _release_application_mutex()
    creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
    )
    try:
        subprocess.Popen(
            [
                str(installer_path),
                "/SILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/CLOSEAPPLICATIONS",
                "/UPDATE=1",
            ],
            cwd=str(installer_path.parent),
            creationflags=creation_flags,
        )
    except OSError:
        logger.exception("Could not start the downloaded Setup.exe")
        _retain_application_mutex()
        self.show()
        QMessageBox.critical(
            self,
            "更新を開始できません",
            "更新プログラムを起動できませんでした。もう一度お試しください。",
        )
        self._remove_pending_installer()
        if isinstance(app, QApplication):
            app.setQuitOnLastWindowClosed(True)
        return
    QApplication.quit()


def _update_download_failed(self: MainWindow, summary: str) -> None:
    self._finish_update_download_dialog()
    self._remove_pending_installer()
    QMessageBox.warning(
        self,
        "更新をダウンロードできません",
        "更新プログラムを取得できませんでした。ネットワーク接続を確認して、"
        f"もう一度お試しください。\n\n詳細: {summary}",
    )


def _update_download_cancelled(self: MainWindow) -> None:
    self._finish_update_download_dialog()
    self._remove_pending_installer()


def _remove_pending_installer(self: MainWindow) -> None:
    if self._pending_installer_directory is not None:
        shutil.rmtree(self._pending_installer_directory, ignore_errors=True)
        self._pending_installer_directory = None
