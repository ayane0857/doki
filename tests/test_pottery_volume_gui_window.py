"""Stale-result handling for the desktop window."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pottery_volume_gui_window import MainWindow
from pottery_volume_gui_workers import AnalysisFinished, WorkerFailed


def test_old_worker_failures_and_results_are_discarded(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(None)

    window.scale_image_edit.setText(str(tmp_path / "new-scale.png"))
    old_scale_generation = window.scale_generation - 1
    window._scale_failed(
        WorkerFailed(old_scale_generation, tmp_path / "old-scale.png", "old error")
    )
    assert "古い解析エラーを破棄" in window.status.text()

    window.image_edit.setText(str(tmp_path / "new-pottery.png"))
    old_analysis_generation = window.analysis_generation - 1
    window._analysis_finished(AnalysisFinished(old_analysis_generation, None))
    assert window.current_analysis is None
    assert "古い解析結果を破棄" in window.status.text()

    window.close()
    app.processEvents()
