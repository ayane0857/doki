"""Main pottery volume application window."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

from pottery_scale import (
    ScaleBarCandidate,
    ScaleTextCandidate,
    has_confident_scale_match,
)
from pottery_volume_cli import AnalysisOutput
from pottery_volume_core import compute_volumes, visualize
from pottery_volume_gui_helpers import Result, build_tsv_row, build_tsv_table


def create_main_window(
    qt: Any,
    analysis_worker: type,
    scale_worker: type,
    pair_worker: type,
    image_dialog: type,
    scale_calibration_dialog: type,
    profile_editor_dialog: type,
) -> type:
    AnalysisWorker = analysis_worker
    ScaleWorker = scale_worker
    PairWorker = pair_worker
    ImageDialog = image_dialog
    ScaleCalibrationDialog = scale_calibration_dialog
    ProfileEditorDialog = profile_editor_dialog
    QApplication = qt.QApplication
    QCheckBox, QComboBox, QDialog = qt.QCheckBox, qt.QComboBox, qt.QDialog
    QFileDialog, QFormLayout, QGridLayout = qt.QFileDialog, qt.QFormLayout, qt.QGridLayout
    QGroupBox, QHBoxLayout, QLabel = qt.QGroupBox, qt.QHBoxLayout, qt.QLabel
    QLineEdit, QMainWindow, QMessageBox = qt.QLineEdit, qt.QMainWindow, qt.QMessageBox
    QPlainTextEdit, QPushButton, QScrollArea = qt.QPlainTextEdit, qt.QPushButton, qt.QScrollArea
    QSpinBox, QSplitter, QTableWidget = qt.QSpinBox, qt.QSplitter, qt.QTableWidget
    QTableWidgetItem, QTextBrowser = qt.QTableWidgetItem, qt.QTextBrowser
    QThread, QVBoxLayout, QWidget, Qt = qt.QThread, qt.QVBoxLayout, qt.QWidget, qt.Qt
    image_filters = (
        "\u753b\u50cf\u30d5\u30a1\u30a4\u30eb (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;"
        "\u3059\u3079\u3066\u306e\u30d5\u30a1\u30a4\u30eb (*)"
    )

    class MainWindow(QMainWindow):
        def __init__(self, initial: str | Path | None) -> None:
            super().__init__()
            self.setWindowTitle("土器体積・容量推定")
            self.resize(1180, 780)
            self.setAcceptDrops(True)
            self.last_info: dict[str, object] | None = None
            self.history: list[dict[str, str]] = []
            self.worker_thread: Any = None
            self.worker: Any = None
            self.scale_thread: Any = None
            self.scale_worker: Any = None
            self.pair_thread: Any = None
            self.pair_worker: Any = None
            self.scale_generation = 0
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
            outer.setContentsMargins(16, 14, 16, 12)
            outer.setSpacing(10)
            title = QLabel("土器体積・容量推定")
            title.setObjectName("appTitle")
            title.setStyleSheet("font-size: 20px; font-weight: bold;")
            outer.addWidget(title)
            self.status = QLabel("画像を選択して「体積・容量を計算する」を押してください。")
            self.status.setObjectName("statusMessage")
            self.status.setWordWrap(True)
            outer.addWidget(self.status)
            splitter = QSplitter(Qt.Horizontal)
            splitter.setChildrenCollapsible(False)
            outer.addWidget(splitter, 1)

            left = QWidget()
            left_layout = QVBoxLayout(left)
            left_layout.setContentsMargins(8, 8, 8, 8)
            left_layout.setSpacing(12)
            files = QGroupBox("画像の選択（ドラッグ＆ドロップ対応）")
            file_form = QFormLayout(files)
            self.image_edit = QLineEdit()
            file_form.addRow("土器実測図", self._path_row(self.image_edit, self.browse_image, "土器画像"))
            self.scale_image_edit = QLineEdit()
            file_form.addRow("目盛り画像", self._path_row(self.scale_image_edit, self.browse_scale, "目盛り画像"))
            left_layout.addWidget(files)

            scale = QGroupBox("スケール（実寸換算）設定")
            scale_form = QFormLayout(scale)
            self.scale_form = scale_form
            self.scale_mode = QComboBox()
            self.scale_mode.addItems(["px（スケール未指定）", "mm/px を直接指定", "スケール線の px と mm", "2点座標と既知 mm", "器高から換算"])
            self.direct_edit = QLineEdit()
            self.bar_px_edit = QLineEdit()
            self.points_edit = QLineEdit()
            self.known_mm_edit = QLineEdit()
            self.height_edit = QLineEdit()
            self.scale_mode.currentTextChanged.connect(self._update_scale_fields)
            scale_form.addRow("指定方法", self.scale_mode)
            scale_form.addRow("mm/px", self.direct_edit)
            scale_form.addRow("線長 (px)", self.bar_px_edit)
            scale_form.addRow("2点座標", self.points_edit)
            scale_form.addRow("実寸 (mm)", self.known_mm_edit)
            scale_form.addRow("器高 (mm)", self.height_edit)
            scale_buttons = QHBoxLayout()
            measure = QPushButton("目盛りを確認・手動修正…")
            measure.clicked.connect(self.measure_scale)
            auto = QPushButton("画像から自動設定…")
            self.auto_scale_button = auto
            auto.clicked.connect(self.auto_scale)
            scale_buttons.addWidget(measure)
            scale_buttons.addWidget(auto)
            scale_form.addRow("", scale_buttons)
            left_layout.addWidget(scale)

            advanced = QGroupBox("詳細設定")
            advanced_form = QFormLayout(advanced)
            self.axis_edit = QLineEdit()
            self.crop_edit = QLineEdit()
            self.liquid_edit = QLineEdit()
            self.kernel_spin = QSpinBox(); self.kernel_spin.setRange(1, 999); self.kernel_spin.setValue(3)
            self.area_spin = QSpinBox(); self.area_spin.setRange(1, 999999); self.area_spin.setValue(5)
            self.smooth_spin = QSpinBox(); self.smooth_spin.setRange(0, 999); self.smooth_spin.setValue(5)
            self.profile_mode = QComboBox(); self.profile_mode.addItems(["auto", "filled", "lines"])
            self.adaptive = QCheckBox("適応的二値化")
            self.debug_edit = QLineEdit()
            self.json_edit = QLineEdit()
            for label, widget in (("回転軸 x", self.axis_edit), ("切り出し x0,y0,x1,y1", self.crop_edit),
                                  ("液面 y", self.liquid_edit), ("閉処理カーネル", self.kernel_spin),
                                  ("最小成分面積", self.area_spin), ("平滑化窓", self.smooth_spin),
                                  ("断面モード", self.profile_mode), ("デバッグ出力先", self.debug_edit),
                                  ("JSON出力先", self.json_edit)):
                advanced_form.addRow(label, widget)
            advanced_form.addRow("", self.adaptive)
            left_layout.addWidget(advanced)
            left_layout.addStretch()
            left_scroll = QScrollArea()
            left_scroll.setWidgetResizable(True)
            left_scroll.setWidget(left)
            splitter.addWidget(left_scroll)

            right = QWidget()
            right_layout = QVBoxLayout(right)
            right_layout.setContentsMargins(8, 8, 8, 8)
            right_layout.setSpacing(12)
            kpi = QGroupBox("推定結果")
            kpi_layout = QGridLayout(kpi)
            self.capacity_label = QLabel("—")
            self.wall_label = QLabel("—")
            self.details_label = QLabel("器高: —\n口径: —\n最大径: —\n全外形体積: —\nパップス検算: —\n適用スケール: —")
            for widget in (self.capacity_label, self.wall_label):
                widget.setStyleSheet("font-size: 18px; font-weight: bold;")
            kpi_layout.addWidget(QLabel("内腔容量"), 0, 0)
            kpi_layout.addWidget(self.capacity_label, 1, 0)
            kpi_layout.addWidget(QLabel("器壁体積"), 0, 1)
            kpi_layout.addWidget(self.wall_label, 1, 1)
            kpi_layout.addWidget(self.details_label, 2, 0, 1, 2)
            right_layout.addWidget(kpi)
            self.log = QPlainTextEdit()
            self.log.setReadOnly(True)
            right_layout.addWidget(QLabel("詳細ログ・注意メッセージ"))
            right_layout.addWidget(self.log, 1)
            splitter.addWidget(right)
            splitter.setSizes([540, 620])

            action = QHBoxLayout()
            self.calculate_button = QPushButton("体積・容量を計算する (Enter)")
            self.calculate_button.setObjectName("primaryAction")
            self.calculate_button.setDefault(True)
            self.calculate_button.clicked.connect(self.calculate)
            action.addWidget(self.calculate_button, 1)
            for text, callback in (("測定履歴", self.show_history), ("ライセンス表記", self.show_license)):
                button = QPushButton(text); button.clicked.connect(callback); action.addWidget(button)
            self.profile_button = QPushButton("輪郭を手動補正")
            self.profile_button.setEnabled(False)
            self.profile_button.clicked.connect(self.edit_profiles)
            action.addWidget(self.profile_button)
            outer.addLayout(action)
            copy_row = QHBoxLayout()
            for text, callback in (("サマリー", self.copy_summary), ("Excel横1行", self.copy_row),
                                   ("ヘッダー付1行", self.copy_header), ("Excel縦の表", self.copy_table)):
                button = QPushButton(text); button.clicked.connect(callback); copy_row.addWidget(button)
            outer.addLayout(copy_row)
            self._update_scale_fields(self.scale_mode.currentText())

        def _path_row(self, edit: Any, callback: Any, kind: str) -> Any:
            row = QWidget(); layout = QHBoxLayout(row); layout.setContentsMargins(0, 0, 0, 0)
            browse = QPushButton("参照…"); browse.clicked.connect(callback)
            preview = QPushButton("確認"); preview.clicked.connect(lambda: self.preview(edit, kind))
            layout.addWidget(edit, 1); layout.addWidget(browse); layout.addWidget(preview)
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
            path, _ = QFileDialog.getOpenFileName(self, "土器実測図を選択", "", image_filters)
            if path:
                self.image_edit.setText(path)
                self.debug_edit.setText(str(Path(path).parent / "debug_out"))
                self.status.setText(f"土器実測図を選択しました: {Path(path).name}")

        def browse_scale(self) -> None:
            path, _ = QFileDialog.getOpenFileName(self, "目盛り画像を選択", "", image_filters)
            if path:
                self.scale_image_edit.setText(path)
                self.auto_scale()

        def preview(self, edit: Any, kind: str) -> None:
            path = Path(edit.text().strip().strip('"'))
            if not path.is_file():
                QMessageBox.warning(self, "画像が見つかりません", str(path)); return
            try:
                ImageDialog(path, kind, self).exec()
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, "画像を表示できません", str(exc))

        def dragEnterEvent(self, event: Any) -> None:
            if event.mimeData().hasUrls(): event.acceptProposedAction()

        def dropEvent(self, event: Any) -> None:
            paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
            paths = [p for p in paths if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}]
            if len(paths) == 1:
                self.image_edit.setText(str(paths[0]))
                self.status.setText("土器画像を選択しました。")
            elif len(paths) >= 2:
                self._start_pair_worker(paths[:2])

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

        def _start_pair_worker(self, paths: list[Path]) -> None:
            if self.pair_thread is not None:
                self.status.setText("現在の画像判別が終わるまでお待ちください。")
                return
            self.status.setText("2枚の画像を判別しています…")
            self._start_background_worker(PairWorker(paths), "pair")

        def _pair_finished(self, payload: object) -> None:
            pottery, scale, labels, bars = cast(tuple[Any, ...], payload)
            self.image_edit.setText(str(pottery))
            self.scale_image_edit.setText(str(scale))
            self._apply_scale_result(labels, bars, scale)

        def _pair_failed(self, message: str) -> None:
            self.status.setText(f"画像の判別に失敗しました: {message}")
            QMessageBox.warning(self, "画像の判別に失敗しました", message)

        def auto_scale(self) -> None:
            path = Path(self.scale_image_edit.text().strip().strip('"') or self.image_edit.text().strip().strip('"'))
            if not path.is_file():
                QMessageBox.warning(self, "画像が未指定です", "目盛り画像または土器画像を選択してください。")
                return
            if self.scale_thread is not None:
                self.status.setText("目盛りの解析が完了するまでお待ちください。")
                return
            self.scale_generation += 1
            self.auto_scale_button.setEnabled(False)
            self.status.setText("目盛り画像を解析しています…")
            self._start_background_worker(
                ScaleWorker(path, self.scale_generation), "scale"
            )

        def _scale_finished(self, payload: object) -> None:
            path, generation, labels, bars = cast(tuple[Any, ...], payload)
            self.auto_scale_button.setEnabled(True)
            current = Path(self.scale_image_edit.text().strip().strip('"') or self.image_edit.text().strip().strip('"'))
            if generation != self.scale_generation or not current.is_file() or path.resolve() != current.resolve():
                return
            self._apply_scale_result(labels, bars, path)

        def _scale_failed(self, message: str) -> None:
            self.auto_scale_button.setEnabled(True)
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
            path = Path(self.scale_image_edit.text().strip().strip('"') or self.image_edit.text().strip().strip('"'))
            if not path.is_file():
                QMessageBox.warning(self, "画像がありません", "先に土器画像か目盛り画像を選択してください。")
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
                if dialog.exec() != QDialog.Accepted:
                    return
                if dialog.mm_per_px is None or dialog.line_pixels is None:
                    raise ValueError("換算値を計算できませんでした。")
                self.direct_edit.setText(f"{dialog.mm_per_px:.10g}")
                self.bar_px_edit.setText(f"{dialog.line_pixels:.2f}")
                self.scale_mode.setCurrentText("mm/px を直接指定")
                self.status.setText(f"手動確認したスケールを設定しました: {dialog.mm_per_px:.6g} mm/px")
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "目盛りを測定できません", str(exc))

        def _arguments(self) -> list[str]:
            image = self.image_edit.text().strip().strip('"')
            if not image: raise ValueError("土器実測図を選択してください。")
            args = [image]
            smooth_window = self.smooth_spin.value()
            if smooth_window != 0 and smooth_window % 2 == 0:
                raise ValueError("\u5e73\u6ed1\u5316\u7a93\u306f0\u307e\u305f\u306f\u5947\u6570\u3067\u6307\u5b9a\u3057\u3066\u304f\u3060\u3055\u3044\u3002")
            mode = self.scale_mode.currentText()
            if mode == "mm/px を直接指定": args += ["--scale-mm-per-px", self.direct_edit.text()]
            elif mode == "スケール線の px と mm": args += ["--scale-bar-px", self.bar_px_edit.text(), "--scale-bar-mm", self.known_mm_edit.text()]
            elif mode == "2点座標と既知 mm": args += ["--scale-points", self.points_edit.text(), "--scale-bar-mm", self.known_mm_edit.text()]
            elif mode == "器高から換算": args += ["--vessel-height-mm", self.height_edit.text()]
            for option, value in (("--axis-x", self.axis_edit.text()), ("--crop", self.crop_edit.text()),
                                  ("--liquid-level-y", self.liquid_edit.text())):
                if value.strip(): args += [option, value]
            args += ["--closing-kernel", str(self.kernel_spin.value()), "--min-component-area", str(self.area_spin.value()),
                     "--smooth-window", str(self.smooth_spin.value()), "--profile-mode", self.profile_mode.currentText()]
            if self.adaptive.isChecked(): args.append("--adaptive-threshold")
            if self.debug_edit.text().strip(): args += ["--debug-dir", self.debug_edit.text().strip()]
            if self.json_edit.text().strip(): args += ["--json-out", self.json_edit.text().strip()]
            return args

        def calculate(self) -> None:
            try: arguments = self._arguments()
            except ValueError as exc: QMessageBox.warning(self, "入力を確認してください", str(exc)); return
            self.calculate_button.setEnabled(False); self.profile_button.setEnabled(False); self.status.setText("\u8a08\u7b97\u4e2d\u2026")
            self.worker_thread = QThread(self); self.worker = AnalysisWorker(arguments)
            self.worker.moveToThread(self.worker_thread)
            self.worker_thread.started.connect(self.worker.run)
            self.worker.finished.connect(self._analysis_finished)
            self.worker.failed.connect(self._analysis_failed)
            self.worker.finished.connect(self.worker_thread.quit); self.worker.failed.connect(self.worker_thread.quit)
            self.worker_thread.finished.connect(lambda: self.calculate_button.setEnabled(True))
            self.worker_thread.finished.connect(self._clear_analysis_worker)
            self.worker_thread.finished.connect(self.worker.deleteLater); self.worker_thread.finished.connect(self.worker_thread.deleteLater)
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

        def _analysis_failed(self, message: str) -> None:
            self.profile_button.setEnabled(self.current_analysis is not None)
            self.log.setPlainText(f"エラー: {message}"); self.status.setText(f"計算エラー: {message}")
            QMessageBox.critical(self, "計算エラー", message)

        def _analysis_finished(self, payload: object) -> None:
            self.current_analysis = cast(AnalysisOutput, payload)
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
            if output.args.json_out:
                try:
                    output.args.json_out.parent.mkdir(parents=True, exist_ok=True)
                    output.args.json_out.write_text(
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
            is_mm = "capacity_ml" in result
            capacity = result["capacity_ml"] if is_mm else result["capacity"]
            wall = result["wall_volume_ml"] if is_mm else result["wall_volume"]
            unit = "mL" if is_mm else str(result["units"]["volume"])
            pappus = result["pappus_wall_volume_ml"] if is_mm else result["pappus_wall_volume"]
            scale = result.get("mm_per_px")
            scale_text = f"{scale:.4f} mm/px" if scale is not None else "\u672a\u6307\u5b9a (px)"
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
                log += ["", "\u3010\u6ce8\u610f\u30fb\u8b66\u544a\u3011"] + [f"\u30fb{item}" for item in output.warnings]
            self.log.setPlainText("\n".join(log))
            self.status.setText(f"\u8a08\u7b97\u5b8c\u4e86: \u5bb9\u91cf {capacity:.2f} {unit}")

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
            if dialog.exec() != QDialog.Accepted:
                return
            try:
                output.profiles = dialog.corrected_profiles
                output.result.update(
                    compute_volumes(
                        output.profiles,
                        output.section.mask,
                        float(output.result["axis_x_px"]),
                        output.mm_per_px,
                        output.section_mode,
                    )
                )
                output.warnings.append("\u65ad\u9762\u30d7\u30ed\u30d5\u30a1\u30a4\u30eb\u3092\u624b\u52d5\u88dc\u6b63\u3057\u307e\u3057\u305f\u3002")
                if output.args.debug_dir:
                    visualize(
                        output.image,
                        float(output.result["axis_x_px"]),
                        output.section,
                        output.profiles,
                        output.mm_per_px,
                        output.args.debug_dir,
                    )
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, "\u518d\u8a08\u7b97\u3067\u304d\u307e\u305b\u3093", str(exc))
                return
            self._refresh_result()
            if self.history:
                self.history[-1] = self._history_row(
                    output.result, Path(str(output.result["input"]))
                )

        def _history_row(self, result: Result, path: Path) -> dict[str, str]:
            is_mm = "capacity_ml" in result
            capacity = result["capacity_ml"] if is_mm else result["capacity"]
            wall = result["wall_volume_ml"] if is_mm else result["wall_volume"]
            pappus = result["pappus_wall_volume_ml"] if is_mm else result["pappus_wall_volume"]
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
                "\u4f53\u7a4d\u5358\u4f4d": "mL" if is_mm else str(result["units"]["volume"]),
            }

        def _copy(self, text: str, message: str) -> None:
            if self.last_info is None: QMessageBox.information(self, "案内", "先に計算を実行してください。"); return
            QApplication.clipboard().setText(text); self.status.setText(message)

        def copy_summary(self) -> None:
            if not self.last_info: self._copy("", ""); return
            self._copy(build_tsv_table(self.last_info), "サマリーをコピーしました。")

        def copy_row(self) -> None:
            self._copy(build_tsv_row(self.last_info) if self.last_info else "", "Excel用横1行をコピーしました。")

        def copy_header(self) -> None:
            self._copy(build_tsv_row(self.last_info, True) if self.last_info else "", "ヘッダー付きデータをコピーしました。")

        def copy_table(self) -> None:
            self._copy(build_tsv_table(self.last_info) if self.last_info else "", "Excel用縦の表をコピーしました。")

        def show_history(self) -> None:
            dialog = QDialog(self); dialog.setWindowTitle("測定履歴一覧"); dialog.resize(1200, 420)
            layout = QVBoxLayout(dialog); table = QTableWidget(len(self.history), 11)
            table.setHorizontalHeaderLabels(["\u753b\u50cf\u30d5\u30a1\u30a4\u30eb", "\u5668\u9ad8", "\u53e3\u5f84", "\u6700\u5927\u5f84", "\u5185\u8154\u5bb9\u91cf", "\u5668\u58c1\u4f53\u7a4d", "\u5168\u5916\u5f62\u4f53\u7a4d", "\u30d1\u30c3\u30d7\u30b9\u691c\u7b97", "\u30d1\u30c3\u30d7\u30b9\u5dee (%)", "\u5bf8\u6cd5\u5358\u4f4d", "\u4f53\u7a4d\u5358\u4f4d"])
            for row, record in enumerate(self.history):
                for col, value in enumerate(record.values()): table.setItem(row, col, QTableWidgetItem(value))
            table.setSelectionBehavior(QTableWidget.SelectRows); layout.addWidget(table)
            close = QPushButton("閉じる"); close.clicked.connect(dialog.accept); layout.addWidget(close); dialog.exec()

        def show_license(self) -> None:
            meipass = getattr(sys, "_MEIPASS", None)
            candidates = [Path(meipass) / "THIRD_PARTY_LICENSES.txt"] if meipass else []
            candidates.append(Path(__file__).resolve().parent / "THIRD_PARTY_LICENSES.txt")
            path = next((item for item in candidates if item.is_file()), None)
            if path is None: QMessageBox.critical(self, "ライセンス表記", "THIRD_PARTY_LICENSES.txt が見つかりません。"); return
            dialog = QDialog(self); dialog.setWindowTitle("ライセンス表記"); dialog.resize(760, 620)
            layout = QVBoxLayout(dialog); text = QTextBrowser(); text.setPlainText(path.read_text(encoding="utf-8")); layout.addWidget(text)
            close = QPushButton("閉じる"); close.clicked.connect(dialog.accept); layout.addWidget(close); dialog.exec()

    return MainWindow
