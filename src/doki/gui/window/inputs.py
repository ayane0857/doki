"""Main window image selection and scale calibration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QMessageBox,
)

from doki.gui.scale_dialog import ImageDialog, ScaleCalibrationDialog
from doki.gui.workers import (
    PairFinished,
    PairWorker,
    ScaleFinished,
    ScaleWorker,
    WorkerFailed,
)
from doki.scale.calibration import (
    ScaleBarCandidate,
    ScaleTextCandidate,
    find_confident_scale_match,
)

if TYPE_CHECKING:
    from doki.gui.window.main import MainWindow


IMAGE_FILTERS = (
    "\u753b\u50cf\u30d5\u30a1\u30a4\u30eb (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;"
    "\u3059\u3079\u3066\u306e\u30d5\u30a1\u30a4\u30eb (*)"
)


def _update_scale_fields(self: MainWindow, mode: str) -> None:
    self.scale_form.setRowVisible(self.direct_edit, mode == "mm/px を直接指定")
    self.scale_form.setRowVisible(self.bar_px_edit, mode == "スケール線の px と mm")
    self.scale_form.setRowVisible(self.points_edit, mode == "2点座標と既知 mm")
    self.scale_form.setRowVisible(
        self.known_mm_edit,
        mode in {"スケール線の px と mm", "2点座標と既知 mm"},
    )
    self.scale_form.setRowVisible(self.height_edit, mode == "器高から換算")


def browse_image(self: MainWindow) -> None:
    path, _ = QFileDialog.getOpenFileName(
        self, "土器実測図を選択", "", IMAGE_FILTERS
    )
    if path:
        self.image_edit.setText(path)
        self.debug_edit.setText(str(Path(path).parent / "debug_out"))
        self.status.setText(f"土器実測図を選択しました: {Path(path).name}")


def browse_scale(self: MainWindow) -> None:
    path, _ = QFileDialog.getOpenFileName(
        self, "目盛り画像を選択", "", IMAGE_FILTERS
    )
    if path:
        self.scale_image_edit.setText(path)
        self.auto_scale()


def preview(self: MainWindow, edit: Any, kind: str) -> None:
    path = Path(edit.text().strip().strip('"'))
    if not path.is_file():
        QMessageBox.warning(self, "画像が見つかりません", str(path))
        return
    try:
        dialog = ImageDialog(path, kind, self)
        dialog.exec()
        dialog.deleteLater()
    except (OSError, ValueError) as exc:
        QMessageBox.critical(self, "画像を表示できません", str(exc))


def dragEnterEvent(self: MainWindow, event: Any) -> None:
    if event.mimeData().hasUrls():
        event.acceptProposedAction()


def dropEvent(self: MainWindow, event: Any) -> None:
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


def _start_background_worker(self: MainWindow, worker: Any, kind: str) -> None:
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


def _clear_background_worker(self: MainWindow, kind: str) -> None:
    setattr(self, f"{kind}_thread", None)
    setattr(self, f"{kind}_worker", None)


def _analysis_input_changed(self: MainWindow, _text: str) -> None:
    self.analysis_generation += 1
    self.pair_generation += 1
    if not self.scale_image_edit.text().strip():
        self.scale_generation += 1


def _scale_input_changed(self: MainWindow, _text: str) -> None:
    self.scale_generation += 1
    self.pair_generation += 1


def _current_scale_path(self: MainWindow) -> Path | None:
    raw_path = self.scale_image_edit.text().strip().strip('"')
    if not raw_path:
        raw_path = self.image_edit.text().strip().strip('"')
    return Path(raw_path) if raw_path else None


def _start_pair_worker(self: MainWindow, paths: tuple[Path, Path]) -> None:
    self.pair_generation += 1
    if self.pair_thread is not None:
        self.status.setText(
            "画像の判別中に新しい画像が選択されました。処理終了後にもう一度ドロップしてください。"
        )
        return
    self.status.setText("2枚の画像を判別しています…")
    self._start_background_worker(PairWorker(paths, self.pair_generation), "pair")


def _pair_finished(self: MainWindow, payload: PairFinished) -> None:
    generation, result = payload.generation, payload.result
    if generation != self.pair_generation:
        self.status.setText("画像が変更されたため、古い判別結果を破棄しました。")
        return
    pottery, scale, labels, bars = result
    self.image_edit.setText(str(pottery))
    self.scale_image_edit.setText(str(scale))
    self._apply_scale_result(labels, bars, scale)


def _pair_failed(self: MainWindow, payload: WorkerFailed) -> None:
    generation, message = payload.generation, payload.summary
    if generation != self.pair_generation:
        return
    self.status.setText(f"画像の判別に失敗しました: {message}")
    QMessageBox.warning(self, "画像の判別に失敗しました", message)


def auto_scale(self: MainWindow) -> None:
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


def _scale_finished(self: MainWindow, payload: ScaleFinished) -> None:
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


def _scale_failed(self: MainWindow, payload: WorkerFailed) -> None:
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
    self: MainWindow,
    labels: list[ScaleTextCandidate],
    bars: list[ScaleBarCandidate],
    path: Path,
) -> None:
    self.scale_labels = labels
    self.scale_bars = bars
    self.scale_detection_path = path.resolve()
    match = find_confident_scale_match(labels, bars)
    self.scale_applied_path = path.resolve()
    self.scale_applied_label = match[0] if match is not None else None
    self.scale_applied_bar = match[1] if match is not None else None
    self.scale_applied_points = (
        ((match[1].x1, match[1].y1), (match[1].x2, match[1].y2))
        if match is not None
        else None
    )
    label = labels[0] if labels else None
    bar = bars[0] if bars else None
    if match is not None:
        label, bar = match
        self.known_mm_edit.setText(f"{label.length_mm:.12g}")
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


def measure_scale(self: MainWindow) -> None:
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
        detection_path_snapshot = self.scale_detection_path
        labels_reference = self.scale_labels
        bars_reference = self.scale_bars
        labels_snapshot = tuple(labels_reference)
        bars_snapshot = tuple(bars_reference)
        applied_label_snapshot = self.scale_applied_label
        applied_bar_snapshot = self.scale_applied_bar
        applied_path_snapshot = self.scale_applied_path
        applied_points_snapshot = self.scale_applied_points
        resolved_path = path.resolve()
        same_detection_image = (
            detection_path_snapshot is not None
            and detection_path_snapshot == resolved_path
        )
        same_applied_image = applied_path_snapshot == resolved_path
        labels = labels_reference if same_detection_image else []
        bars = bars_reference if same_detection_image else []
        selected_label = self.scale_applied_label if same_applied_image else None
        selected_bar = self.scale_applied_bar if same_applied_image else None
        selected_points = self.scale_applied_points if same_applied_image else None
        try:
            default_mm = float(self.known_mm_edit.text().strip())
        except ValueError:
            default_mm = None
        dialog = ScaleCalibrationDialog(
            path,
            labels,
            bars,
            default_mm,
            self,
            selected_label=selected_label,
            selected_bar=selected_bar,
            selected_points=selected_points,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            dialog.deleteLater()
            return
        detection_state_unchanged = (
            self.scale_detection_path == detection_path_snapshot
            and self.scale_labels is labels_reference
            and self.scale_bars is bars_reference
            and tuple(self.scale_labels) == labels_snapshot
            and tuple(self.scale_bars) == bars_snapshot
            and self.scale_applied_label is applied_label_snapshot
            and self.scale_applied_bar is applied_bar_snapshot
            and self.scale_applied_path == applied_path_snapshot
            and self.scale_applied_points == applied_points_snapshot
        )
        if not detection_state_unchanged:
            dialog.deleteLater()
            return

        confirmed_length_mm = dialog.length_mm
        mm_per_px = dialog.mm_per_px
        line_pixels = dialog.line_pixels
        line_points = dialog.line_points
        if (
            mm_per_px is None
            or line_pixels is None
            or confirmed_length_mm is None
            or line_points is None
        ):
            dialog.deleteLater()
            raise ValueError("換算値を計算できませんでした。")
        self.known_mm_edit.setText(f"{confirmed_length_mm:.12g}")
        selected_label = dialog.label_combo.currentData()
        self.scale_applied_label = (
            selected_label
            if isinstance(selected_label, ScaleTextCandidate)
            else None
        )
        selected_bar_index = dialog.bar_combo.currentIndex()
        self.scale_applied_bar = (
            dialog.bars[selected_bar_index]
            if 0 <= selected_bar_index < len(dialog.bars)
            else None
        )
        self.scale_applied_path = resolved_path
        self.scale_applied_points = line_points
        dialog.deleteLater()
        self.scale_generation += 1
        self.direct_edit.setText(f"{mm_per_px:.10g}")
        self.bar_px_edit.setText(f"{line_pixels:.2f}")
        self.scale_mode.setCurrentText("mm/px を直接指定")
        self.status.setText(
            f"手動確認したスケールを設定しました: {mm_per_px:.6g} mm/px"
        )
    except (OSError, ValueError) as exc:
        QMessageBox.warning(self, "目盛りを測定できません", str(exc))
