"""Stale-result handling for the desktop window."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTableWidgetSelectionRange

from pottery_volume_gui_window import HistoryTable, MainWindow
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


@pytest.mark.parametrize("key", [Qt.Key.Key_Delete, Qt.Key.Key_Backspace])
def test_history_table_clears_selected_cells_with_delete_or_backspace(key):
    app = QApplication.instance() or QApplication([])
    records = [
        {
            "画像ファイル": "vessel.png",
            "器高": "12.3",
            "最大径": "45.6",
        }
    ]
    table = HistoryTable(records)
    table.show()
    table.setRangeSelected(QTableWidgetSelectionRange(0, 0, 0, 1), True)
    table.setFocus()
    app.processEvents()

    QTest.keyClick(table, key)

    assert table.item(0, 0).text() == ""
    assert table.item(0, 1).text() == ""
    assert table.item(0, 3).text() == "45.6"
    assert records[0]["画像ファイル"] == ""
    assert records[0]["器高"] == ""
    assert records[0]["最大径"] == "45.6"

    table.close()
    app.processEvents()
