"""Main window analysis parameters and background worker lifecycle."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QMessageBox,
)

from doki.analysis.core import parse_crop, parse_points
from doki.cli import AnalysisParams
from doki.gui.workers import (
    AnalysisFinished,
    AnalysisWorker,
    WorkerFailed,
)

if TYPE_CHECKING:
    from doki.gui.window.main import MainWindow


def _optional_float(self: MainWindow, text: str, label: str) -> float | None:
    value = text.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{label}は数値で指定してください。") from exc


def _analysis_params(self: MainWindow) -> AnalysisParams:
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


def calculate(self: MainWindow) -> None:
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


def _clear_analysis_worker(self: MainWindow) -> None:
    self.worker_thread = None
    self.worker = None


def _analysis_failed(self: MainWindow, payload: WorkerFailed) -> None:
    input_path = payload.source
    generation = payload.generation
    message = payload.summary
    current_text = self.image_edit.text().strip().strip('"')
    if self.current_analysis is not None:
        retained_path = self.current_analysis.params.input_path
        same_retained_image = bool(current_text) and self._same_path(
            retained_path, Path(current_text)
        )
    else:
        same_retained_image = False
    self.profile_button.setEnabled(same_retained_image)
    for button in self.result_copy_buttons:
        button.setEnabled(same_retained_image)
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


def _analysis_finished(self: MainWindow, payload: AnalysisFinished) -> None:
    generation, output = payload.generation, payload.output
    current_text = self.image_edit.text().strip().strip('"')
    if (
        generation != self.analysis_generation
        or not current_text
        or not self._same_path(output.params.input_path, Path(current_text))
    ):
        same_retained_image = False
        if self.current_analysis is not None and current_text:
            same_retained_image = self._same_path(
                self.current_analysis.params.input_path, Path(current_text)
            )
        self.profile_button.setEnabled(same_retained_image)
        for button in self.result_copy_buttons:
            button.setEnabled(same_retained_image)
        self.status.setText("画像が変更されたため、古い解析結果を破棄しました。")
        return
    self.current_analysis = output
    self.profile_button.setEnabled(True)
    self._refresh_result()
    result = self.current_analysis.result
    path = Path(str(result["input"]))
    self.history.append(self._history_row(result, path))
