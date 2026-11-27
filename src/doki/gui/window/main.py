"""Main pottery volume application window."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, QThread
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QSpinBox,
)

from doki.cli import AnalysisOutput
from doki.gui.helpers import (
    Info,
)
from doki.gui.window import analysis as _analysis
from doki.gui.window import history as _history
from doki.gui.window import inputs as _inputs
from doki.gui.window import layout as _layout
from doki.gui.window import results as _results
from doki.gui.window import updates as _updates
from doki.gui.window.history import HISTORY_HEADERS as HISTORY_HEADERS
from doki.gui.window.history import HistoryTable as HistoryTable
from doki.gui.window.inputs import IMAGE_FILTERS as IMAGE_FILTERS
from doki.gui.workers import (
    AnalysisWorker,
    PairWorker,
    ScaleWorker,
    SetupDownloadWorker,
    UpdateCheckWorker,
)
from doki.scale.calibration import (
    ScaleBarCandidate,
    ScaleTextCandidate,
)


class MainWindow(QMainWindow):
    status: QLabel
    image_edit: QLineEdit
    scale_image_edit: QLineEdit
    scale_form: QFormLayout
    scale_mode: QComboBox
    direct_edit: QLineEdit
    bar_px_edit: QLineEdit
    points_edit: QLineEdit
    known_mm_edit: QLineEdit
    height_edit: QLineEdit
    auto_scale_button: QPushButton
    axis_edit: QLineEdit
    crop_edit: QLineEdit
    liquid_edit: QLineEdit
    kernel_spin: QSpinBox
    area_spin: QSpinBox
    smooth_spin: QSpinBox
    profile_mode: QComboBox
    adaptive: QCheckBox
    debug_edit: QLineEdit
    json_edit: QLineEdit
    capacity_label: QLabel
    wall_label: QLabel
    details_label: QLabel
    log: QPlainTextEdit
    calculate_button: QPushButton
    profile_button: QPushButton
    result_copy_buttons: list[QPushButton]
    theme_actions: dict[str, QAction]
    dark_mode_action: QAction
    check_updates_action: QAction
    automatic_updates_action: QAction

    def __init__(
        self,
        initial: str | Path | None,
        *,
        build_version: str = "dev",
        build_commit: str = "dev",
    ) -> None:
        super().__init__()
        self.build_version = build_version
        self.build_commit = build_commit
        title_version = f"v{build_version}" if build_version != "dev" else "開発版"
        self.setWindowTitle(f"土器体積・容量推定 ({title_version})")
        self.resize(1100, 700)
        self.setAcceptDrops(True)
        self.last_info: Info | None = None
        self.history: list[dict[str, str]] = []
        self.worker_thread: QThread | None = None
        self.worker: AnalysisWorker | None = None
        self.scale_thread: QThread | None = None
        self.scale_worker: ScaleWorker | None = None
        self.pair_thread: QThread | None = None
        self.pair_worker: PairWorker | None = None
        self.update_check_thread: QThread | None = None
        self.update_check_worker: UpdateCheckWorker | None = None
        self.update_download_thread: QThread | None = None
        self.update_download_worker: SetupDownloadWorker | None = None
        self.update_progress_dialog: QProgressDialog | None = None
        self._pending_setup_installer_path: Path | None = None
        self._update_check_manual = False
        self._pending_installer_directory: Path | None = None
        self._settings = QSettings()
        self.analysis_generation = 0
        self.scale_generation = 0
        self.pair_generation = 0
        self.scale_labels: list[ScaleTextCandidate] = []
        self.scale_bars: list[ScaleBarCandidate] = []
        self.scale_applied_label: ScaleTextCandidate | None = None
        self.scale_applied_bar: ScaleBarCandidate | None = None
        self.scale_applied_path: Path | None = None
        self.scale_applied_points: (
            tuple[tuple[float, float], tuple[float, float]] | None
        ) = None
        self.scale_detection_path: Path | None = None
        self.current_analysis: AnalysisOutput | None = None
        self._build_ui()
        self._build_view_menu()
        if initial:
            self.image_edit.setText(str(initial))

    # Bind the extracted handlers to this QObject for Qt signal delivery.
    _build_ui = _layout._build_ui
    _build_view_menu = _layout._build_view_menu
    _set_theme = _layout._set_theme
    _path_row = _layout._path_row

    check_updates_on_startup = _updates.check_updates_on_startup
    check_for_updates_manually = _updates.check_for_updates_manually
    _start_update_check = _updates._start_update_check
    _clear_update_check_worker = _updates._clear_update_check_worker
    _update_check_finished = _updates._update_check_finished
    _update_check_failed = _updates._update_check_failed
    _show_update_available = _updates._show_update_available
    _download_update_setup = _updates._download_update_setup
    _update_download_progress = _updates._update_download_progress
    _finish_update_download_dialog = _updates._finish_update_download_dialog
    _clear_update_download_worker = _updates._clear_update_download_worker
    _update_download_ready = _updates._update_download_ready
    _finish_update_download_thread = _updates._finish_update_download_thread
    _update_download_finished = _updates._update_download_finished
    _update_download_failed = _updates._update_download_failed
    _update_download_cancelled = _updates._update_download_cancelled
    _remove_pending_installer = _updates._remove_pending_installer

    _update_scale_fields = _inputs._update_scale_fields
    browse_image = _inputs.browse_image
    browse_scale = _inputs.browse_scale
    preview = _inputs.preview
    dragEnterEvent = _inputs.dragEnterEvent
    dropEvent = _inputs.dropEvent
    _start_background_worker = _inputs._start_background_worker
    _clear_background_worker = _inputs._clear_background_worker
    _analysis_input_changed = _inputs._analysis_input_changed
    _scale_input_changed = _inputs._scale_input_changed
    _current_scale_path = _inputs._current_scale_path
    _start_pair_worker = _inputs._start_pair_worker
    _pair_finished = _inputs._pair_finished
    _pair_failed = _inputs._pair_failed
    auto_scale = _inputs.auto_scale
    _scale_finished = _inputs._scale_finished
    _scale_failed = _inputs._scale_failed
    _apply_scale_result = _inputs._apply_scale_result
    measure_scale = _inputs.measure_scale

    _optional_float = _analysis._optional_float
    _analysis_params = _analysis._analysis_params
    calculate = _analysis.calculate
    _clear_analysis_worker = _analysis._clear_analysis_worker
    _analysis_failed = _analysis._analysis_failed
    _analysis_finished = _analysis._analysis_finished

    _refresh_result = _results._refresh_result
    _copy_last_info = _results._copy_last_info
    _copy_text_summary = _results._copy_text_summary
    edit_profiles = _results.edit_profiles

    _history_row = _history._history_row
    show_history = _history.show_history
    show_license = _history.show_license

    @staticmethod
    def _same_path(path_a: Path, path_b: Path) -> bool:
        return path_a.resolve() == path_b.resolve()

    def closeEvent(self, event: Any) -> None:
        workers = (
            self.worker_thread,
            self.scale_thread,
            self.pair_thread,
            self.update_check_thread,
            self.update_download_thread,
        )
        if any(thread is not None and thread.isRunning() for thread in workers):
            QMessageBox.information(
                self,
                "処理中です",
                "処理が終わってからウィンドウを閉じてください。"
                "更新プログラムのダウンロードはキャンセルできます。",
            )
            event.ignore()
            return
        event.accept()
