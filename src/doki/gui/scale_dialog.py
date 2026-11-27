"""Scale image preview and manual calibration dialogs."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from doki.analysis.core import read_image
from doki.analysis.geometry import pixel_distance
from doki.gui.scale_canvas import ScaleCanvas as ScaleCanvas
from doki.scale.calibration import ScaleBarCandidate, ScaleTextCandidate, rank_scale_bars


class ImageDialog(QDialog):
    def __init__(self, path: Path, title: str, parent: Any) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{title} - {path.name}")
        self.resize(900, 700)
        image = read_image(path)
        height, width = image.shape[:2]
        rgb = image[:, :, ::-1].copy()
        qimage = QImage(rgb.data, width, height, width * 3, QImage.Format.Format_RGB888).copy()
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setPixmap(QPixmap.fromImage(qimage))
        label.setScaledContents(False)
        scroll = QScrollArea()
        scroll.setWidget(label)
        scroll.setWidgetResizable(True)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        layout.addWidget(QLabel(f"{path.name} ({width} × {height} px)"))
        close = QPushButton("閉じる")
        close.clicked.connect(self.accept)
        layout.addWidget(close)


class ScaleCalibrationDialog(QDialog):
    def __init__(
        self,
        path: Path,
        labels: list[ScaleTextCandidate],
        bars: list[ScaleBarCandidate],
        default_length_mm: float | None,
        parent: Any,
        *,
        selected_label: ScaleTextCandidate | None = None,
        selected_bar: ScaleBarCandidate | None = None,
        selected_points: tuple[tuple[float, float], tuple[float, float]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"目盛り線を確認・修正 - {path.name}")
        self.resize(1180, 760)
        self.mm_per_px: float | None = None
        self.line_pixels: float | None = None
        self.length_mm: float | None = None
        self.line_points: tuple[tuple[float, float], tuple[float, float]] | None = None
        self.image = read_image(path)
        self.all_labels = labels
        self.all_bars = bars
        self.default_length_mm = default_length_mm

        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "候補線を選び、赤い端点をドラッグして調整できます。候補がない場合は画像上を2回クリックしてください。"
        ))
        body = QHBoxLayout()
        self.canvas = ScaleCanvas(self.image)
        body.addWidget(self.canvas, 1)
        panel = QWidget()
        panel.setMinimumWidth(290)
        form = QFormLayout(panel)
        self.label_combo = QComboBox()
        matching_index = None
        if selected_label is not None:
            selected_label_index = next(
                (
                    index
                    for index, item in enumerate(labels)
                    if item is selected_label or item == selected_label
                ),
                None,
            )
            if selected_label_index is not None and (
                default_length_mm is None
                or math.isclose(
                    labels[selected_label_index].length_mm,
                    default_length_mm,
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                )
            ):
                matching_index = selected_label_index
        if matching_index is None and default_length_mm is not None:
            matching_index = next(
                (
                    index
                    for index, item in enumerate(labels)
                    if math.isclose(
                        item.length_mm,
                        default_length_mm,
                        rel_tol=1e-9,
                        abs_tol=1e-9,
                    )
                ),
                None,
            )
        keep_current_length = default_length_mm is not None and matching_index is None
        if keep_current_length:
            self.label_combo.addItem(
                f"現在の長さを維持（{default_length_mm:g} mm）", None
            )
        if labels:
            for item in labels:
                self.label_combo.addItem(
                    f"{item.text}  ·  {item.length_mm:g} mm  ·  OCR {item.confidence:.0%}",
                    item,
                )
        elif not keep_current_length:
            self.label_combo.addItem("OCRなし（長さを入力）", None)
        if matching_index is not None:
            self.label_combo.setCurrentIndex(
                matching_index + int(keep_current_length)
            )
        form.addRow("読み取った長さ", self.label_combo)

        self.length_spin = QDoubleSpinBox()
        self.length_spin.setRange(0, 1_000_000_000)
        self.length_spin.setDecimals(12)
        self.length_spin.setValue(max(0.0, default_length_mm or 0.0))
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["mm", "cm", "m"])
        length_row = QWidget()
        length_layout = QHBoxLayout(length_row)
        length_layout.setContentsMargins(0, 0, 0, 0)
        length_layout.addWidget(self.length_spin, 1)
        length_layout.addWidget(self.unit_combo)
        form.addRow("実際の長さ", length_row)

        self.bar_combo = QComboBox()
        form.addRow("検出した線", self.bar_combo)
        self.readout = QLabel("線の長さ: —\n換算値: —")
        self.readout.setWordWrap(True)
        form.addRow("現在の選択", self.readout)
        clear = QPushButton("手動線をリセット")
        clear.clicked.connect(self.canvas.clear_manual_points)
        fit = QPushButton("全体を表示")
        fit.clicked.connect(self.canvas.fit_image)
        tools = QHBoxLayout()
        tools.addWidget(clear)
        tools.addWidget(fit)
        form.addRow("", tools)
        form.addRow(QLabel("ホイール: 拡大縮小 / 右ドラッグ: 移動\n線上クリック: 候補選択 / 端点ドラッグ: 微調整"))
        body.addWidget(panel)
        outer.addLayout(body, 1)

        self.status = QLabel("目盛り線と長さを確認してください。")
        outer.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("この換算値を使う")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("キャンセル")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self.label_combo.currentIndexChanged.connect(self._label_changed)
        self.bar_combo.currentIndexChanged.connect(self._bar_changed)
        self.length_spin.valueChanged.connect(self._update_readout)
        self.unit_combo.currentTextChanged.connect(self._update_readout)
        self.canvas.on_changed = self._update_readout
        self.canvas.on_candidate_clicked = self._select_candidate
        self._label_changed(
            update_length=default_length_mm is None,
            preferred_bar=selected_bar,
            preferred_points=selected_points,
        )

    def _label_changed(
        self,
        *_args: Any,
        update_length: bool = True,
        preferred_bar: ScaleBarCandidate | None = None,
        preferred_points: tuple[tuple[float, float], tuple[float, float]] | None = None,
    ) -> None:
        label = self.label_combo.currentData()
        if label is not None and update_length:
            self.length_spin.setValue(label.value)
            self.unit_combo.setCurrentText(label.unit)
        elif label is None and update_length and self.default_length_mm is not None:
            self.length_spin.setValue(max(0.0, self.default_length_mm))
            self.unit_combo.setCurrentText("mm")
        selected = label if label is not None else (self.all_labels[0] if self.all_labels else None)
        self.bars = rank_scale_bars(self.all_bars, selected, self.image.shape)
        self.bar_combo.blockSignals(True)
        self.bar_combo.clear()
        if self.bars:
            for index, bar in enumerate(self.bars):
                self.bar_combo.addItem(
                    f"{index + 1}: {bar.pixels:.1f} px  ·  y={(bar.y1 + bar.y2) / 2:.0f}  ·  信頼度 {bar.confidence:.0%}"
                )
            selected_bar_index = next(
                (
                    index
                    for index, bar in enumerate(self.bars)
                    if preferred_bar is not None
                    and (bar is preferred_bar or bar == preferred_bar)
                ),
                0,
            )
            self.bar_combo.setCurrentIndex(selected_bar_index)
        else:
            self.bar_combo.addItem("候補なし（画像をクリックして指定）")
            selected_bar_index = -1
        self.bar_combo.blockSignals(False)
        self.canvas.set_candidates(self.all_labels, self.bars, selected_bar_index)
        if preferred_points is not None:
            self.canvas.manual_points = list(preferred_points)
        self._update_readout()

    def _bar_changed(self, index: int) -> None:
        self.canvas.set_candidates(self.all_labels, self.bars, index)
        self._update_readout()

    def _select_candidate(self, index: int) -> None:
        if 0 <= index < self.bar_combo.count():
            self.bar_combo.setCurrentIndex(index)

    def _selected_points(self) -> list[tuple[float, float]]:
        if len(self.canvas.manual_points) == 2:
            return list(self.canvas.manual_points)
        index = self.bar_combo.currentIndex()
        if 0 <= index < len(self.bars):
            bar = self.bars[index]
            return [(bar.x1, bar.y1), (bar.x2, bar.y2)]
        return []

    def _update_readout(self, *_args: Any) -> None:
        points = self._selected_points()
        if len(points) != 2:
            self.readout.setText("線の長さ: 未選択\n換算値: —")
            self.status.setText("候補線を選ぶか、線の両端を指定してください。")
            return
        pixels = pixel_distance(points[0], points[1])
        unit_scale = {"mm": 1.0, "cm": 10.0, "m": 1000.0}[self.unit_combo.currentText()]
        length_mm = self.length_spin.value() * unit_scale
        mm_per_px = length_mm / pixels if pixels > 0 else 0
        self.readout.setText(f"線の長さ: {pixels:.2f} px\n換算値: {mm_per_px:.7g} mm/px")
        self.status.setText(
            f"端点 ({points[0][0]:.1f}, {points[0][1]:.1f}) → "
            f"({points[1][0]:.1f}, {points[1][1]:.1f})"
        )

    def accept(self) -> None:
        points = self._selected_points()
        if len(points) != 2:
            QMessageBox.warning(self, "線を選択してください", "候補線を選ぶか、線の両端を指定してください。")
            return
        pixels = pixel_distance(points[0], points[1])
        if pixels <= 0:
            QMessageBox.warning(self, "線を確認してください", "線の長さが0 pxです。")
            return
        unit_scale = {"mm": 1.0, "cm": 10.0, "m": 1000.0}[self.unit_combo.currentText()]
        length_mm = self.length_spin.value() * unit_scale
        if length_mm <= 0:
            QMessageBox.warning(self, "実寸を入力してください", "目盛り線の実寸は0より大きい値にしてください。")
            return
        self.line_pixels = pixels
        self.length_mm = length_mm
        self.line_points = (points[0], points[1])
        self.mm_per_px = length_mm / pixels
        super().accept()
