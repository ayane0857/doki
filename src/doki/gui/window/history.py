"""Main window history table and supplementary dialogs."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from doki.gui.helpers import (
    Result,
)

if TYPE_CHECKING:
    from doki.gui.window.main import MainWindow


HISTORY_HEADERS = (
    "画像ファイル",
    "器高",
    "口径",
    "最大径",
    "内腔容量",
    "器壁体積",
    "全外形体積",
    "パップス検算",
    "パップス差 (%)",
    "寸法単位",
    "体積単位",
)


class HistoryTable(QTableWidget):
    """Spreadsheet-like history grid with copy and cell-clearing support."""

    copied = Signal(str)

    def __init__(
        self, records: list[dict[str, str]], parent: QWidget | None = None
    ) -> None:
        super().__init__(len(records), len(HISTORY_HEADERS), parent)
        self._records = records
        self.setHorizontalHeaderLabels(list(HISTORY_HEADERS))
        for row, record in enumerate(records):
            for col, header in enumerate(HISTORY_HEADERS):
                item = QTableWidgetItem(record.get(header, ""))
                if col:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.setItem(row, col, item)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.setShowGrid(True)
        self.setCornerButtonEnabled(True)  # top-left corner = select all
        self.verticalHeader().setDefaultSectionSize(24)
        self.resizeColumnsToContents()
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        if records:
            self.setCurrentCell(0, 0)

    def selection_tsv(self, with_header: bool = False) -> str:
        """Return the selected cells as TSV; the bounding box is used like Excel."""
        indexes = self.selectedIndexes()
        if not indexes:
            return ""
        selected = {(index.row(), index.column()) for index in indexes}
        rows = range(min(r for r, _ in selected), max(r for r, _ in selected) + 1)
        cols = range(min(c for _, c in selected), max(c for _, c in selected) + 1)
        lines: list[str] = []
        if with_header:
            lines.append("\t".join(HISTORY_HEADERS[c] for c in cols))
        for row in rows:
            cells: list[str] = []
            for col in cols:
                item = self.item(row, col) if (row, col) in selected else None
                text = item.text() if item else ""
                text = text.replace("\t", " ").replace("\r", " ").replace("\n", " ")
                # The file-name column is free text: keep Excel from running it as a formula.
                if col == 0 and text.startswith(("=", "+", "-", "@")):
                    text = "'" + text
                cells.append(text)
            lines.append("\t".join(cells))
        return "\n".join(lines)

    def copy_selection(self, with_header: bool = False) -> None:
        text = self.selection_tsv(with_header)
        if not text:
            return
        QApplication.clipboard().setText(text)
        row_count = text.count("\n") + 1 - (1 if with_header else 0)
        self.copied.emit(
            f"{row_count}行をコピーしました。Excelにそのまま貼り付けできます。"
        )

    def keyPressEvent(self, event: Any) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            for index in self.selectedIndexes():
                item = self.item(index.row(), index.column())
                if item is not None:
                    item.setText("")
                self._records[index.row()][HISTORY_HEADERS[index.column()]] = ""
            event.accept()
            return
        super().keyPressEvent(event)

    def _show_menu(self, position: Any) -> None:
        menu = QMenu(self)
        copy = menu.addAction("コピー (Ctrl+C)")
        copy_header = menu.addAction("見出し付きでコピー")
        menu.addSeparator()
        select_all = menu.addAction("すべて選択 (Ctrl+A)")
        has_selection = bool(self.selectedIndexes())
        copy.setEnabled(has_selection)
        copy_header.setEnabled(has_selection)
        chosen = menu.exec(self.viewport().mapToGlobal(position))
        if chosen is copy:
            self.copy_selection()
        elif chosen is copy_header:
            self.copy_selection(with_header=True)
        elif chosen is select_all:
            self.selectAll()


def _history_row(self: MainWindow, result: Result, path: Path) -> dict[str, str]:
    is_mm = result["mm_per_px"] is not None
    capacity = (
        cast(float, result.get("capacity_ml")) if is_mm else result["capacity"]
    )
    wall = (
        cast(float, result.get("wall_volume_ml"))
        if is_mm
        else result["wall_volume"]
    )
    pappus = (
        cast(float, result.get("pappus_wall_volume_ml"))
        if is_mm
        else result["pappus_wall_volume"]
    )
    return {
        "\u753b\u50cf\u30d5\u30a1\u30a4\u30eb": path.name,
        "\u5668\u9ad8": f"{result['vessel_height']:.2f}",
        "\u53e3\u5f84": f"{result['mouth_diameter']:.2f}",
        "\u6700\u5927\u5f84": f"{result['maximum_diameter']:.2f}",
        "\u5185\u8154\u5bb9\u91cf": f"{capacity:.2f}",
        "\u5668\u58c1\u4f53\u7a4d": f"{wall:.2f}",
        "\u5168\u5916\u5f62\u4f53\u7a4d": f"{capacity + wall:.2f}",
        "\u30d1\u30c3\u30d7\u30b9\u691c\u7b97": f"{pappus:.2f}",
        "\u30d1\u30c3\u30d7\u30b9\u5dee (%)": f"{result['pappus_difference_percent']:.2f}",
        "\u5bf8\u6cd5\u5358\u4f4d": str(result["units"]["length"]),
        "\u4f53\u7a4d\u5358\u4f4d": (
            "mL" if is_mm else str(result["units"]["volume"])
        ),
    }


def show_history(self: MainWindow) -> None:
    dialog = QDialog(self)
    dialog.setWindowTitle("測定履歴一覧")
    dialog.resize(1200, 420)
    layout = QVBoxLayout(dialog)
    hint = QLabel(
        "セルをドラッグ・Shift/Ctrl+クリックで選択し、Ctrl+C でコピーできます。"
        "Delete/Backspace で選択セルの内容を消去できます。"
        "列見出し・行番号のクリックで列・行ごと選択、右クリックで見出し付きコピー。"
    )
    hint.setObjectName("caption")
    hint.setWordWrap(True)
    layout.addWidget(hint)
    table = HistoryTable(self.history)
    table.copied.connect(hint.setText)
    layout.addWidget(table, 1)
    close = QPushButton("閉じる")
    close.clicked.connect(dialog.accept)
    layout.addWidget(close)
    dialog.exec()
    dialog.deleteLater()


def show_license(self: MainWindow) -> None:
    meipass = getattr(sys, "_MEIPASS", None)
    candidates = [Path(meipass) / "THIRD_PARTY_LICENSES.txt"] if meipass else []
    candidates.append(Path(__file__).resolve().parents[3] / "THIRD_PARTY_LICENSES.txt")
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        QMessageBox.critical(
            self, "ライセンス表記", "THIRD_PARTY_LICENSES.txt が見つかりません。"
        )
        return
    dialog = QDialog(self)
    dialog.setWindowTitle("ライセンス表記")
    dialog.resize(760, 620)
    layout = QVBoxLayout(dialog)
    text = QTextBrowser()
    text.setPlainText(path.read_text(encoding="utf-8"))
    layout.addWidget(text)
    close = QPushButton("閉じる")
    close.clicked.connect(dialog.accept)
    layout.addWidget(close)
    dialog.exec()
    dialog.deleteLater()
