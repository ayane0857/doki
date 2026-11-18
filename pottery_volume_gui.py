"""PySide6 GUI for pottery volume estimation."""

from __future__ import annotations

import sys
from pathlib import Path

from pottery_volume_gui_helpers import (
    GUIArgumentParser,
    Info,
    Result,
    build_tsv_row,
    build_tsv_table,
    pixel_distance,
)
from pottery_volume_gui_profiles import create_profile_editor_class
from pottery_volume_gui_qt import load_qt
from pottery_volume_gui_scale import create_scale_dialog_classes
from pottery_volume_gui_window import create_main_window
from pottery_volume_gui_workers import create_worker_classes


def launch_gui(initial_image: str | Path | None = None) -> None:
    """Open the PySide6 desktop interface."""
    qt = load_qt()
    AnalysisWorker, ScaleWorker, PairWorker = create_worker_classes(qt)
    ImageDialog, ScaleCalibrationDialog = create_scale_dialog_classes(qt)
    ProfileEditorDialog = create_profile_editor_class(qt)
    MainWindow = create_main_window(
        qt,
        AnalysisWorker,
        ScaleWorker,
        PairWorker,
        ImageDialog,
        ScaleCalibrationDialog,
        ProfileEditorDialog,
    )
    QApplication = qt.QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(
        """
        QWidget { color: #172033; font-family: 'Yu Gothic UI', 'Meiryo UI', sans-serif; font-size: 10pt; }
        QMainWindow, QDialog { background: #f3f6fb; }
        QLabel#appTitle { color: #111827; font-size: 21pt; font-weight: 700; }
        QLabel#statusMessage { background: #e8f0ff; color: #1e3a66; border: 1px solid #cbdaf5; border-radius: 8px; padding: 9px 12px; }
        QGroupBox { background: #ffffff; border: 1px solid #d8e0eb; border-radius: 9px; margin-top: 12px; padding: 12px 10px 10px; font-weight: 600; }
        QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #334155; }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextBrowser, QTableWidget { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 5px 7px; selection-background-color: #bfdbfe; }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTableWidget:focus { border: 1px solid #4f8de8; }
        QPushButton { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 7px; padding: 7px 11px; }
        QPushButton:hover { background: #eff6ff; border-color: #93b4e8; }
        QPushButton:pressed { background: #dbeafe; }
        QPushButton:disabled { color: #94a3b8; background: #eef1f5; }
        QPushButton#primaryAction { background: #2563eb; border: 1px solid #1d4ed8; color: #ffffff; font-weight: 700; padding: 10px 14px; }
        QPushButton#primaryAction:hover { background: #1d4ed8; }
        QSplitter::handle { background: #e2e8f0; width: 5px; }
        QHeaderView::section { background: #eef3f9; border: 0; border-bottom: 1px solid #d8e0eb; padding: 6px; font-weight: 600; }
        """
    )
    window = MainWindow(initial_image)
    window.show()
    app.exec()
