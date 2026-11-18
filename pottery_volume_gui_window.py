"""Main pottery volume application window."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from pottery_scale import (
    ScaleBarCandidate,
    ScaleTextCandidate,
    has_confident_scale_match,
)
from pottery_volume_cli import AnalysisOutput, AnalysisParams
from pottery_volume_core import compute_volumes, parse_crop, parse_points, visualize
from pottery_volume_gui_helpers import Info, Result
from pottery_volume_gui_profiles import ProfileEditorDialog
from pottery_volume_gui_scale import ImageDialog, ScaleCalibrationDialog
from pottery_volume_gui_workers import (
    AnalysisFinished,
    AnalysisWorker,
    PairFinished,
    PairWorker,
    ScaleFinished,
    ScaleWorker,
    WorkerFailed,
)

IMAGE_FILTERS = (
    "\u753b\u50cf\u30d5\u30a1\u30a4\u30eb (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;"
    "\u3059\u3079\u3066\u306e\u30d5\u30a1\u30a4\u30eb (*)"
)


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
    """Read-only grid that selects and copies like an Excel sheet."""

    copied = Signal(str)

    def __init__(
        self, records: list[dict[str, str]], parent: QWidget | None = None
    ) -> None:
        super().__init__(len(records), len(HISTORY_HEADERS), parent)
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


class MainWindow(QMainWindow):
    def __init__(self, initial: str | Path | None) -> None:
        super().__init__()
        self.setWindowTitle("土器体積・容量推定")
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
        self.analysis_generation = 0
        self.scale_generation = 0
        self.pair_generation = 0
        self.scale_labels: list[ScaleTextCandidate] = []
        self.scale_bars: list[ScaleBarCandidate] = []
        self.scale_detection_path: Path | None = None
        self.current_analysis: AnalysisOutput | None = None
        self._build_ui()
        if initial:
            self.image_edit.setText(str(initial))

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)
        self.status = QLabel(
            "画像を選択（ドラッグ＆ドロップ可）して「体積・容量を計算する」を押してください。"
        )
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter, 1)

        # Left: inputs
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.setSpacing(6)

        files = QGroupBox("画像")
        file_form = QFormLayout(files)
        self.image_edit = QLineEdit()
        self.image_edit.textChanged.connect(self._analysis_input_changed)
        file_form.addRow(
            "土器実測図", self._path_row(self.image_edit, self.browse_image, "土器画像")
        )
        self.scale_image_edit = QLineEdit()
        self.scale_image_edit.textChanged.connect(self._scale_input_changed)
        file_form.addRow(
            "目盛り画像",
            self._path_row(self.scale_image_edit, self.browse_scale, "目盛り画像"),
        )
        left_layout.addWidget(files)

        scale = QGroupBox("スケール")
        form = QFormLayout(scale)
        self.scale_form = form
        self.scale_mode = QComboBox()
        self.scale_mode.addItems(
            [
                "px（スケール未指定）",
                "mm/px を直接指定",
                "スケール線の px と mm",
                "2点座標と既知 mm",
                "器高から換算",
            ]
        )
        self.direct_edit = QLineEdit()
        self.bar_px_edit = QLineEdit()
        self.points_edit = QLineEdit()
        self.known_mm_edit = QLineEdit()
        self.height_edit = QLineEdit()
        self.scale_mode.currentTextChanged.connect(self._update_scale_fields)
        form.addRow("指定方法", self.scale_mode)
        form.addRow("mm/px", self.direct_edit)
        form.addRow("線長 (px)", self.bar_px_edit)
        form.addRow("2点座標", self.points_edit)
        form.addRow("実寸 (mm)", self.known_mm_edit)
        form.addRow("器高 (mm)", self.height_edit)
        scale_buttons = QHBoxLayout()
        measure = QPushButton("目盛りを確認・手動修正…")
        measure.clicked.connect(self.measure_scale)
        auto = QPushButton("画像から自動設定…")
        self.auto_scale_button = auto
        auto.clicked.connect(self.auto_scale)
        scale_buttons.addWidget(measure)
        scale_buttons.addWidget(auto)
        form.addRow("", scale_buttons)
        left_layout.addWidget(scale)

        # Advanced settings: a checkable box that stays folded until ticked.
        self.axis_edit = QLineEdit()
        self.crop_edit = QLineEdit()
        self.liquid_edit = QLineEdit()
        self.kernel_spin = QSpinBox()
        self.kernel_spin.setRange(1, 999)
        self.kernel_spin.setValue(3)
        self.area_spin = QSpinBox()
        self.area_spin.setRange(1, 999999)
        self.area_spin.setValue(5)
        self.smooth_spin = QSpinBox()
        self.smooth_spin.setRange(0, 999)
        self.smooth_spin.setValue(5)
        self.profile_mode = QComboBox()
        self.profile_mode.addItems(["auto", "filled", "lines"])
        self.adaptive = QCheckBox("適応的二値化")
        self.debug_edit = QLineEdit()
        self.json_edit = QLineEdit()
        advanced = QGroupBox("詳細設定")
        advanced.setCheckable(True)
        advanced.setChecked(False)
        advanced_body = QWidget()
        advanced_form = QFormLayout(advanced_body)
        advanced_form.setContentsMargins(0, 0, 0, 0)
        for label, widget in (
            ("回転軸 x", self.axis_edit),
            ("切り出し x0,y0,x1,y1", self.crop_edit),
            ("液面 y", self.liquid_edit),
            ("閉処理カーネル", self.kernel_spin),
            ("最小成分面積", self.area_spin),
            ("平滑化窓", self.smooth_spin),
            ("断面モード", self.profile_mode),
            ("デバッグ出力先", self.debug_edit),
            ("JSON出力先", self.json_edit),
        ):
            advanced_form.addRow(label, widget)
        advanced_form.addRow("", self.adaptive)
        advanced_layout = QVBoxLayout(advanced)
        advanced_layout.addWidget(advanced_body)
        advanced_body.setVisible(False)
        advanced.toggled.connect(advanced_body.setVisible)
        left_layout.addWidget(advanced)
        left_layout.addStretch()
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        left_scroll.setWidget(left)
        splitter.addWidget(left_scroll)

        # Right: results and log
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.setSpacing(6)
        result_box = QGroupBox("推定結果")
        result_grid = QGridLayout(result_box)
        self.capacity_label = QLabel("—")
        self.wall_label = QLabel("—")
        self.details_label = QLabel(
            "器高: —\n口径: —\n最大径: —\n全外形体積: —\nパップス検算: —\n適用スケール: —"
        )
        self.details_label.setObjectName("details")
        for widget in (self.capacity_label, self.wall_label):
            widget.setObjectName("bigValue")
        for column, text in enumerate(("内腔容量", "器壁体積")):
            caption = QLabel(text)
            caption.setObjectName("caption")
            result_grid.addWidget(caption, 0, column)
        result_grid.addWidget(self.capacity_label, 1, 0)
        result_grid.addWidget(self.wall_label, 1, 1)
        result_grid.addWidget(self.details_label, 2, 0, 1, 2)
        right_layout.addWidget(result_box)
        log_box = QGroupBox("ログ・注意メッセージ")
        log_layout = QVBoxLayout(log_box)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        log_layout.addWidget(self.log)
        right_layout.addWidget(log_box, 1)
        splitter.addWidget(right)
        splitter.setSizes([500, 540])

        action = QHBoxLayout()
        self.calculate_button = QPushButton("体積・容量を計算する (Enter)")
        self.calculate_button.setObjectName("primaryAction")
        self.calculate_button.setDefault(True)
        self.calculate_button.clicked.connect(self.calculate)
        action.addWidget(self.calculate_button, 1)
        for text, callback in (
            ("測定履歴", self.show_history),
            ("ライセンス表記", self.show_license),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            action.addWidget(button)
        self.profile_button = QPushButton("輪郭を手動補正")
        self.profile_button.setEnabled(False)
        self.profile_button.clicked.connect(self.edit_profiles)
        action.addWidget(self.profile_button)
        outer.addLayout(action)
        self._update_scale_fields(self.scale_mode.currentText())

    def _path_row(self, edit: Any, callback: Any, kind: str) -> Any:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        browse = QPushButton("参照…")
        browse.clicked.connect(callback)
        preview = QPushButton("確認")
        preview.clicked.connect(lambda: self.preview(edit, kind))
        layout.addWidget(edit, 1)
        layout.addWidget(browse)
        layout.addWidget(preview)
        return row

    def _update_scale_fields(self, mode: str) -> None:
        self.scale_form.setRowVisible(self.direct_edit, mode == "mm/px を直接指定")
        self.scale_form.setRowVisible(self.bar_px_edit, mode == "スケール線の px と mm")
        self.scale_form.setRowVisible(self.points_edit, mode == "2点座標と既知 mm")
        self.scale_form.setRowVisible(
            self.known_mm_edit,
            mode in {"スケール線の px と mm", "2点座標と既知 mm"},
        )
        self.scale_form.setRowVisible(self.height_edit, mode == "器高から換算")

    def browse_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "土器実測図を選択", "", IMAGE_FILTERS
        )
        if path:
            self.image_edit.setText(path)
            self.debug_edit.setText(str(Path(path).parent / "debug_out"))
            self.status.setText(f"土器実測図を選択しました: {Path(path).name}")

    def browse_scale(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "目盛り画像を選択", "", IMAGE_FILTERS
        )
        if path:
            self.scale_image_edit.setText(path)
            self.auto_scale()

    def preview(self, edit: Any, kind: str) -> None:
        path = Path(edit.text().strip().strip('"'))
        if not path.is_file():
            QMessageBox.warning(self, "画像が見つかりません", str(path))
            return
        try:
            ImageDialog(path, kind, self).exec()
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "画像を表示できません", str(exc))

    def dragEnterEvent(self, event: Any) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: Any) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        paths = [
            p
            for p in paths
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
        ]
        if len(paths) == 1:
            self.image_edit.setText(str(paths[0]))
            self.status.setText("土器画像を選択しました。")
        elif len(paths) >= 2:
            self._start_pair_worker((paths[0], paths[1]))

    def _start_background_worker(self, worker: Any, kind: str) -> None:
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(getattr(self, f"_{kind}_finished"))
        worker.failed.connect(getattr(self, f"_{kind}_failed"))
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._clear_background_worker(kind))
        setattr(self, f"{kind}_thread", thread)
        setattr(self, f"{kind}_worker", worker)
        thread.start()

    def _clear_background_worker(self, kind: str) -> None:
        setattr(self, f"{kind}_thread", None)
        setattr(self, f"{kind}_worker", None)

    def _analysis_input_changed(self, _text: str) -> None:
        self.analysis_generation += 1
        self.pair_generation += 1
        if not self.scale_image_edit.text().strip():
            self.scale_generation += 1

    def _scale_input_changed(self, _text: str) -> None:
        self.scale_generation += 1
        self.pair_generation += 1

    def _current_scale_path(self) -> Path | None:
        raw_path = self.scale_image_edit.text().strip().strip('"')
        if not raw_path:
            raw_path = self.image_edit.text().strip().strip('"')
        return Path(raw_path) if raw_path else None

    @staticmethod
    def _same_path(path_a: Path, path_b: Path) -> bool:
        return path_a.resolve() == path_b.resolve()

    def _start_pair_worker(self, paths: tuple[Path, Path]) -> None:
        self.pair_generation += 1
        if self.pair_thread is not None:
            self.status.setText(
                "画像の判別中に新しい画像が選択されました。処理終了後にもう一度ドロップしてください。"
            )
            return
        self.status.setText("2枚の画像を判別しています…")
        self._start_background_worker(PairWorker(paths, self.pair_generation), "pair")

    def _pair_finished(self, payload: PairFinished) -> None:
        generation, result = payload.generation, payload.result
        if generation != self.pair_generation:
            self.status.setText("画像が変更されたため、古い判別結果を破棄しました。")
            return
        pottery, scale, labels, bars = result
        self.image_edit.setText(str(pottery))
        self.scale_image_edit.setText(str(scale))
        self._apply_scale_result(labels, bars, scale)

    def _pair_failed(self, payload: WorkerFailed) -> None:
        generation, message = payload.generation, payload.summary
        if generation != self.pair_generation:
            return
        self.status.setText(f"画像の判別に失敗しました: {message}")
        QMessageBox.warning(self, "画像の判別に失敗しました", message)

    def auto_scale(self) -> None:
        path = self._current_scale_path()
        if path is None or not path.is_file():
            QMessageBox.warning(
                self, "画像が未指定です", "目盛り画像または土器画像を選択してください。"
            )
            return
        if self.scale_thread is not None:
            self.scale_generation += 1
            self.status.setText("目盛りの解析が完了するまでお待ちください。")
            return
        self.scale_generation += 1
        self.auto_scale_button.setEnabled(False)
        self.status.setText("目盛り画像を解析しています…")
        self._start_background_worker(ScaleWorker(path, self.scale_generation), "scale")

    def _scale_finished(self, payload: ScaleFinished) -> None:
        path = payload.path
        generation = payload.generation
        labels = payload.labels
        bars = payload.bars
        self.auto_scale_button.setEnabled(True)
        current = self._current_scale_path()
        if (
            current is None
            or generation != self.scale_generation
            or not self._same_path(path, current)
        ):
            self.status.setText(
                "目盛り画像が変更されたため、古い解析結果を破棄しました。必要なら自動設定を再実行してください。"
            )
            return
        self._apply_scale_result(labels, bars, path)

    def _scale_failed(self, payload: WorkerFailed) -> None:
        path = payload.source
        generation = payload.generation
        message = payload.summary
        self.auto_scale_button.setEnabled(True)
        current = self._current_scale_path()
        if (
            current is None
            or generation != self.scale_generation
            or not isinstance(path, Path)
            or not self._same_path(path, current)
        ):
            self.status.setText(
                "目盛り画像が変更されたため、古い解析エラーを破棄しました。必要なら自動設定を再実行してください。"
            )
            return
        self.status.setText(f"目盛りの解析に失敗しました: {message}")
        QMessageBox.warning(self, "目盛りの解析に失敗しました", message)

    def _apply_scale_result(
        self,
        labels: list[ScaleTextCandidate],
        bars: list[ScaleBarCandidate],
        path: Path,
    ) -> None:
        self.scale_labels = labels
        self.scale_bars = bars
        self.scale_detection_path = path.resolve()
        label = labels[0] if labels else None
        bar = bars[0] if bars else None
        if (
            label is not None
            and bar is not None
            and has_confident_scale_match(labels, bars)
        ):
            self.known_mm_edit.setText(f"{label.length_mm:g}")
            self.bar_px_edit.setText(f"{bar.pixels:.2f}")
            self.scale_mode.setCurrentText("スケール線の px と mm")
            confidence = f"線の信頼度 {bar.confidence:.0%}"
            self.status.setText(
                f"自動候補: {label.text} = {label.length_mm:g} mm / "
                f"線 {bar.pixels:.2f} px（{confidence}）。画像上で確認・修正できます。"
            )
        elif label is not None and bar is not None:
            self.status.setText(
                f"候補 {label.text} / {bar.pixels:.2f} px は検出しましたが、"
                "誤設定防止のため自動適用しません。"
                "「目盛りを確認・手動修正…」で線と実寸を確認してください。"
                "現在のスケール設定は変更していません。"
            )
        elif label is not None:
            self.status.setText(
                f"長さ {label.text} ({label.length_mm:g} mm) を読み取りました。"
                "現在のスケール設定は変更していません。線を画像上で指定してください。"
            )
        elif bar is not None:
            self.status.setText(
                f"目盛り線候補 {bar.pixels:.2f} px を検出しました。"
                "現在のスケール設定は変更していません。実寸を入力して確認してください。"
            )
        else:
            self.status.setText(
                "自動検出できる候補がありませんでした。現在のスケール設定は変更していません。"
                "画像上で線の両端と実寸を指定できます。"
            )

    def measure_scale(self) -> None:
        path = Path(
            self.scale_image_edit.text().strip().strip('"')
            or self.image_edit.text().strip().strip('"')
        )
        if not path.is_file():
            QMessageBox.warning(
                self, "画像がありません", "先に土器画像か目盛り画像を選択してください。"
            )
            return
        try:
            candidate_path = self.scale_detection_path
            same_image = candidate_path is not None and candidate_path == path.resolve()
            labels = self.scale_labels if same_image else []
            bars = self.scale_bars if same_image else []
            try:
                default_mm = float(self.known_mm_edit.text().strip())
            except ValueError:
                default_mm = None
            dialog = ScaleCalibrationDialog(path, labels, bars, default_mm, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            if dialog.mm_per_px is None or dialog.line_pixels is None:
                raise ValueError("換算値を計算できませんでした。")
            self.direct_edit.setText(f"{dialog.mm_per_px:.10g}")
            self.bar_px_edit.setText(f"{dialog.line_pixels:.2f}")
            self.scale_mode.setCurrentText("mm/px を直接指定")
            self.status.setText(
                f"手動確認したスケールを設定しました: {dialog.mm_per_px:.6g} mm/px"
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "目盛りを測定できません", str(exc))

    def _optional_float(self, text: str, label: str) -> float | None:
        value = text.strip()
        if not value:
            return None
        try:
            return float(value)
        except ValueError as exc:
            raise ValueError(f"{label}は数値で指定してください。") from exc

    def _analysis_params(self) -> AnalysisParams:
        image = self.image_edit.text().strip().strip('"')
        if not image:
            raise ValueError("土器実測図を選択してください。")
        smooth_window = self.smooth_spin.value()
        if smooth_window != 0 and smooth_window % 2 == 0:
            raise ValueError(
                "\u5e73\u6ed1\u5316\u7a93\u306f0\u307e\u305f\u306f\u5947\u6570\u3067\u6307\u5b9a\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
            )
        mode = self.scale_mode.currentText()
        scale_mm_per_px = None
        scale_bar_px = None
        scale_bar_mm = None
        scale_points = None
        vessel_height_mm = None
        if mode == "mm/px を直接指定":
            scale_mm_per_px = self._optional_float(self.direct_edit.text(), "mm/px")
            if scale_mm_per_px is None:
                raise ValueError("mm/px を入力してください。")
        elif mode == "スケール線の px と mm":
            scale_bar_px = self._optional_float(self.bar_px_edit.text(), "線長")
            scale_bar_mm = self._optional_float(self.known_mm_edit.text(), "実寸")
            if scale_bar_px is None or scale_bar_mm is None:
                raise ValueError("線長 (px) と実寸 (mm) を入力してください。")
        elif mode == "2点座標と既知 mm":
            points_text = self.points_edit.text().strip()
            if not points_text:
                raise ValueError("2点座標を入力してください。")
            try:
                scale_points = parse_points(points_text)
            except argparse.ArgumentTypeError as exc:
                raise ValueError(str(exc)) from exc
            scale_bar_mm = self._optional_float(self.known_mm_edit.text(), "実寸")
            if scale_bar_mm is None:
                raise ValueError("実寸 (mm) を入力してください。")
        elif mode == "器高から換算":
            vessel_height_mm = self._optional_float(self.height_edit.text(), "器高")
            if vessel_height_mm is None:
                raise ValueError("器高 (mm) を入力してください。")

        crop_text = self.crop_edit.text().strip()
        try:
            crop = parse_crop(crop_text) if crop_text else None
        except argparse.ArgumentTypeError as exc:
            raise ValueError(str(exc)) from exc
        debug_text = self.debug_edit.text().strip()
        json_text = self.json_edit.text().strip()
        return AnalysisParams(
            input_path=Path(image),
            scale_mm_per_px=scale_mm_per_px,
            scale_bar_px=scale_bar_px,
            scale_bar_mm=scale_bar_mm,
            scale_points=scale_points,
            vessel_height_mm=vessel_height_mm,
            axis_x=self._optional_float(self.axis_edit.text(), "回転軸 x"),
            crop=crop,
            liquid_level_y=self._optional_float(self.liquid_edit.text(), "液面 y"),
            closing_kernel=self.kernel_spin.value(),
            profile_mode=self.profile_mode.currentText(),
            min_component_area=self.area_spin.value(),
            smooth_window=smooth_window,
            adaptive_threshold=self.adaptive.isChecked(),
            debug_dir=Path(debug_text) if debug_text else None,
            json_out=Path(json_text) if json_text else None,
        )

    def calculate(self) -> None:
        if self.worker_thread is not None:
            self.analysis_generation += 1
            self.status.setText("現在の画像解析が終わるまでお待ちください。")
            return
        try:
            params = self._analysis_params()
        except ValueError as exc:
            QMessageBox.warning(self, "入力を確認してください", str(exc))
            return
        self.analysis_generation += 1
        generation = self.analysis_generation
        self.calculate_button.setEnabled(False)
        self.profile_button.setEnabled(False)
        self.status.setText("計算中…")
        self.worker_thread = QThread(self)
        self.worker = AnalysisWorker(params, generation)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._analysis_finished)
        self.worker.failed.connect(self._analysis_failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(
            lambda: self.calculate_button.setEnabled(True)
        )
        self.worker_thread.finished.connect(self._clear_analysis_worker)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.start()

    def _clear_analysis_worker(self) -> None:
        self.worker_thread = None
        self.worker = None

    def closeEvent(self, event: Any) -> None:
        workers = (self.worker_thread, self.scale_thread, self.pair_thread)
        if any(thread is not None and thread.isRunning() for thread in workers):
            QMessageBox.information(
                self,
                "\u51e6\u7406\u4e2d\u3067\u3059",
                "\u753b\u50cf\u51e6\u7406\u304c\u7d42\u308f\u3063\u3066\u304b\u3089\u30a6\u30a3\u30f3\u30c9\u30a6\u3092\u9589\u3058\u3066\u304f\u3060\u3055\u3044\u3002",
            )
            event.ignore()
            return
        event.accept()

    def _analysis_failed(self, payload: WorkerFailed) -> None:
        input_path = payload.source
        generation = payload.generation
        message = payload.summary
        self.profile_button.setEnabled(self.current_analysis is not None)
        current_text = self.image_edit.text().strip().strip('"')
        if (
            generation != self.analysis_generation
            or not current_text
            or not isinstance(input_path, Path)
            or not self._same_path(input_path, Path(current_text))
        ):
            self.status.setText("画像が変更されたため、古い解析エラーを破棄しました。")
            return
        self.log.setPlainText(f"エラー: {message}")
        self.status.setText(f"計算エラー: {message}")
        QMessageBox.critical(self, "計算エラー", message)

    def _analysis_finished(self, payload: AnalysisFinished) -> None:
        generation, output = payload.generation, payload.output
        current_text = self.image_edit.text().strip().strip('"')
        if (
            generation != self.analysis_generation
            or not current_text
            or not self._same_path(output.params.input_path, Path(current_text))
        ):
            self.profile_button.setEnabled(self.current_analysis is not None)
            self.status.setText("画像が変更されたため、古い解析結果を破棄しました。")
            return
        self.current_analysis = output
        self.profile_button.setEnabled(True)
        self._refresh_result()
        result = self.current_analysis.result
        path = Path(str(result["input"]))
        self.history.append(self._history_row(result, path))

    def _refresh_result(self) -> None:
        output = self.current_analysis
        if output is None:
            return
        result = output.result
        path = Path(str(result["input"]))
        if output.params.json_out:
            try:
                output.params.json_out.parent.mkdir(parents=True, exist_ok=True)
                output.params.json_out.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except (OSError, UnicodeError) as exc:
                QMessageBox.warning(self, "JSON save failed", str(exc))
        self.last_info = {
            "title": path.stem,
            "image_name": path.name,
            "image_path": str(path),
            "result": result,
        }
        length = str(result["units"]["length"])
        if "capacity_ml" in result:
            capacity = result["capacity_ml"]
            wall = cast(float, result.get("wall_volume_ml"))
            pappus = cast(float, result.get("pappus_wall_volume_ml"))
            unit = "mL"
        else:
            capacity = result["capacity"]
            wall = result["wall_volume"]
            pappus = result["pappus_wall_volume"]
            unit = str(result["units"]["volume"])
        scale = result.get("mm_per_px")
        scale_text = (
            f"{scale:.4f} mm/px" if scale is not None else "\u672a\u6307\u5b9a (px)"
        )
        self.capacity_label.setText(f"{capacity:.2f} {unit}")
        self.wall_label.setText(f"{wall:.2f} {unit}")
        self.details_label.setText(
            f"\u5668\u9ad8: {result['vessel_height']:.2f} {length}\n"
            f"\u53e3\u5f84: {result['mouth_diameter']:.2f} {length}\n"
            f"\u6700\u5927\u5f84: {result['maximum_diameter']:.2f} {length}\n"
            f"\u5168\u5916\u5f62\u4f53\u7a4d: {capacity + wall:.2f} {unit}\n"
            f"\u30d1\u30c3\u30d7\u30b9\u691c\u7b97: {pappus:.2f} {unit} "
            f"({result['pappus_difference_percent']:.2f}%)\n"
            f"\u9069\u7528\u30b9\u30b1\u30fc\u30eb: {scale_text}"
        )
        log = [
            f"\u5bfe\u8c61\u30d5\u30a1\u30a4\u30eb: {path.name}",
            f"\u65ad\u9762\u30e2\u30fc\u30c9: {output.section_mode}",
            "\u8f2a\u90ed\u30fb\u56de\u8ee2\u8ef8\u306e\u691c\u51fa\u306f\u6b63\u5e38\u306b\u5b8c\u4e86\u3057\u307e\u3057\u305f\u3002",
        ]
        if output.warnings:
            log += ["", "\u3010\u6ce8\u610f\u30fb\u8b66\u544a\u3011"] + [
                f"\u30fb{item}" for item in output.warnings
            ]
        self.log.setPlainText("\n".join(log))
        self.status.setText(
            f"\u8a08\u7b97\u5b8c\u4e86: \u5bb9\u91cf {capacity:.2f} {unit}"
        )

    def edit_profiles(self) -> None:
        output = self.current_analysis
        if output is None:
            return
        dialog = ProfileEditorDialog(
            output.profiles,
            output.image,
            float(output.result["axis_x_px"]),
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            output.profiles = dialog.corrected_profiles
            recomputed = compute_volumes(
                output.profiles,
                output.section.mask,
                float(output.result["axis_x_px"]),
                output.mm_per_px,
                output.section_mode,
            )
            cast(dict[str, Any], output.result).update(cast(dict[str, Any], recomputed))
            output.warnings.append(
                "\u65ad\u9762\u30d7\u30ed\u30d5\u30a1\u30a4\u30eb\u3092\u624b\u52d5\u88dc\u6b63\u3057\u307e\u3057\u305f\u3002"
            )
            if output.params.debug_dir:
                visualize(
                    output.image,
                    float(output.result["axis_x_px"]),
                    output.section,
                    output.profiles,
                    output.mm_per_px,
                    output.params.debug_dir,
                )
        except (OSError, ValueError) as exc:
            QMessageBox.critical(
                self, "\u518d\u8a08\u7b97\u3067\u304d\u307e\u305b\u3093", str(exc)
            )
            return
        self._refresh_result()
        if self.history:
            self.history[-1] = self._history_row(
                output.result, Path(str(output.result["input"]))
            )

    def _history_row(self, result: Result, path: Path) -> dict[str, str]:
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

    def show_history(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("測定履歴一覧")
        dialog.resize(1200, 420)
        layout = QVBoxLayout(dialog)
        hint = QLabel(
            "セルをドラッグ・Shift/Ctrl+クリックで選択し、Ctrl+C でコピーできます。"
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

    def show_license(self) -> None:
        meipass = getattr(sys, "_MEIPASS", None)
        candidates = [Path(meipass) / "THIRD_PARTY_LICENSES.txt"] if meipass else []
        candidates.append(Path(__file__).resolve().parent / "THIRD_PARTY_LICENSES.txt")
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
