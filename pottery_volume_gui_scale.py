"""Scale image preview and manual calibration dialogs."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
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

from pottery_scale import ScaleBarCandidate, ScaleTextCandidate, rank_scale_bars
from pottery_volume_core import read_image
from pottery_volume_geometry import pixel_distance


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

class ScaleCanvas(QWidget):
    """Zoomable image canvas for choosing and adjusting scale-bar endpoints."""

    def __init__(self, image: np.ndarray, parent: Any = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(640, 430)
        self.setMouseTracking(True)
        self.image_height, self.image_width = image.shape[:2]
        rgb = image[:, :, ::-1].copy() if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
        qimage = QImage(
            rgb.data, self.image_width, self.image_height,
            self.image_width * 3, QImage.Format.Format_RGB888,
        ).copy()
        self.pixmap = QPixmap.fromImage(qimage)
        self._rendered_pixmap: Any = None
        self._rendered_size = (0, 0)
        self.scale = min(1.0, 800 / self.image_width, 560 / self.image_height)
        self.offset_x = 12.0
        self.offset_y = 12.0
        self.bars: list[ScaleBarCandidate] = []
        self.labels: list[ScaleTextCandidate] = []
        self.selected_index = -1
        self.manual_points: list[tuple[float, float]] = []
        self.on_changed: Any = None
        self.on_candidate_clicked: Any = None
        self._pan_anchor: tuple[float, float] | None = None
        self._pan_origin: tuple[float, float] = (0.0, 0.0)
        self._drag_endpoint: int | None = None

    def set_candidates(
        self,
        labels: list[ScaleTextCandidate],
        bars: list[ScaleBarCandidate],
        selected_index: int,
    ) -> None:
        self.labels = labels
        self.bars = bars
        self.selected_index = selected_index
        self.manual_points = []
        self.update()

    def clear_manual_points(self) -> None:
        self.manual_points = []
        self.update()
        if self.on_changed:
            self.on_changed()

    def fit_image(self) -> None:
        self.scale = min(
            1.0,
            max(0.05, (self.width() - 24) / self.image_width),
            max(0.05, (self.height() - 24) / self.image_height),
        )
        self.offset_x = (self.width() - self.image_width * self.scale) / 2
        self.offset_y = (self.height() - self.image_height * self.scale) / 2
        self.update()

    def _to_image(self, x: float, y: float) -> tuple[float, float] | None:
        ix = (x - self.offset_x) / self.scale
        iy = (y - self.offset_y) / self.scale
        if ix < 0 or iy < 0 or ix >= self.image_width or iy >= self.image_height:
            return None
        return ix, iy

    def _display_points(self) -> list[tuple[float, float]]:
        if len(self.manual_points) == 2:
            return self.manual_points
        if 0 <= self.selected_index < len(self.bars):
            bar = self.bars[self.selected_index]
            return [(bar.x1, bar.y1), (bar.x2, bar.y2)]
        return []

    def _screen_point(self, point: tuple[float, float]) -> QPointF:
        return QPointF(
            self.offset_x + point[0] * self.scale,
            self.offset_y + point[1] * self.scale,
        )

    def _scaled_image(self) -> Any:
        size = (
            max(1, round(self.image_width * self.scale)),
            max(1, round(self.image_height * self.scale)),
        )
        if size != self._rendered_size:
            self._rendered_pixmap = self.pixmap.scaled(
                *size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self._rendered_size = size
        return self._rendered_pixmap

    @staticmethod
    def _segment_distance(point: QPointF, start: QPointF, end: QPointF) -> float:
        dx, dy = end.x() - start.x(), end.y() - start.y()
        denominator = dx * dx + dy * dy
        if denominator == 0:
            return math.hypot(point.x() - start.x(), point.y() - start.y())
        t = max(0.0, min(1.0, ((point.x() - start.x()) * dx + (point.y() - start.y()) * dy) / denominator))
        return math.hypot(point.x() - (start.x() + t * dx), point.y() - (start.y() + t * dy))

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#172033"))
        shown = self._scaled_image()
        painter.drawPixmap(round(self.offset_x), round(self.offset_y), shown)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        for label in self.labels:
            x0, y0, x1, y1 = label.bounds
            painter.setPen(QPen(QColor("#2dd4bf"), 2))
            painter.drawRect(
                round(self.offset_x + x0 * self.scale),
                round(self.offset_y + y0 * self.scale),
                max(1, round((x1 - x0) * self.scale)),
                max(1, round((y1 - y0) * self.scale)),
            )

        for index, bar in enumerate(self.bars):
            start, end = self._screen_point((bar.x1, bar.y1)), self._screen_point((bar.x2, bar.y2))
            selected = index == self.selected_index and not self.manual_points
            painter.setPen(QPen(QColor("#fbbf24" if selected else "#38bdf8"), 4 if selected else 2))
            painter.drawLine(start, end)

        points = self._display_points()
        if len(points) == 2:
            start, end = self._screen_point(points[0]), self._screen_point(points[1])
            painter.setPen(QPen(QColor("#fb7185"), 4))
            painter.drawLine(start, end)
            painter.setBrush(QColor("#fff"))
            for point in (start, end):
                painter.setPen(QPen(QColor("#fb7185"), 3))
                painter.drawEllipse(point, 7, 7)
        elif len(self.manual_points) == 1:
            point = self._screen_point(self.manual_points[0])
            painter.setBrush(QColor("#fff"))
            painter.setPen(QPen(QColor("#fb7185"), 3))
            painter.drawEllipse(point, 7, 7)
        painter.end()

    def mousePressEvent(self, event: Any) -> None:
        x, y = event.position().x(), event.position().y()
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._pan_anchor = (x, y)
            self._pan_origin = (self.offset_x, self.offset_y)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        image_point = self._to_image(x, y)
        if image_point is None:
            return

        # Grab a detected endpoint to make sub-pixel corrections with drag.
        points = self._display_points()
        if len(points) == 2 and len(self.manual_points) != 1:
            distances = [math.hypot(x - p.x(), y - p.y()) for p in map(self._screen_point, points)]
            closest = int(np.argmin(distances))
            if distances[closest] <= 16:
                if not self.manual_points:
                    self.manual_points = list(points)
                self._drag_endpoint = closest
                self.update()
                return

        # Clicking any detected rail selects it directly. Endpoint handles
        # are checked first so a rail can still be fine-tuned by dragging.
        screen_point = QPointF(x, y)
        if not self.manual_points and self.on_candidate_clicked:
            nearest: tuple[float, int] | None = None
            for index, bar in enumerate(self.bars):
                distance = self._segment_distance(
                    screen_point,
                    self._screen_point((bar.x1, bar.y1)),
                    self._screen_point((bar.x2, bar.y2)),
                )
                if distance <= 9 and (nearest is None or distance < nearest[0]):
                    nearest = (distance, index)
            if nearest is not None:
                self.on_candidate_clicked(nearest[1])
                return

        if len(self.manual_points) == 2:
            self.manual_points.clear()
        self.manual_points.append(image_point)
        self.update()
        if self.on_changed:
            self.on_changed()

    def mouseMoveEvent(self, event: Any) -> None:
        x, y = event.position().x(), event.position().y()
        if self._pan_anchor is not None:
            self.offset_x = self._pan_origin[0] + x - self._pan_anchor[0]
            self.offset_y = self._pan_origin[1] + y - self._pan_anchor[1]
            self.update()
            return
        if self._drag_endpoint is not None:
            point = self._to_image(x, y)
            if point is not None:
                self.manual_points[self._drag_endpoint] = point
                self.update()
                if self.on_changed:
                    self.on_changed()

    def mouseReleaseEvent(self, _event: Any) -> None:
        self._pan_anchor = None
        self._drag_endpoint = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def wheelEvent(self, event: Any) -> None:
        steps = event.angleDelta().y() / 120
        if not steps:
            return
        old_scale = self.scale
        new_scale = max(0.03, min(8.0, old_scale * (1.2 ** steps)))
        x, y = event.position().x(), event.position().y()
        image_x = (x - self.offset_x) / old_scale
        image_y = (y - self.offset_y) / old_scale
        self.scale = new_scale
        self.offset_x = x - image_x * new_scale
        self.offset_y = y - image_y * new_scale
        self.update()

class ScaleCalibrationDialog(QDialog):
    def __init__(
        self,
        path: Path,
        labels: list[ScaleTextCandidate],
        bars: list[ScaleBarCandidate],
        default_length_mm: float | None,
        parent: Any,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"目盛り線を確認・修正 - {path.name}")
        self.resize(1180, 760)
        self.mm_per_px: float | None = None
        self.line_pixels: float | None = None
        self.image = read_image(path)
        self.all_labels = labels
        self.all_bars = bars

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
        if labels:
            for item in labels:
                self.label_combo.addItem(
                    f"{item.text}  ·  {item.length_mm:g} mm  ·  OCR {item.confidence:.0%}",
                    item,
                )
        else:
            self.label_combo.addItem("OCRなし（長さを入力）", None)
        form.addRow("読み取った長さ", self.label_combo)

        self.length_spin = QDoubleSpinBox()
        self.length_spin.setRange(0, 1_000_000_000)
        self.length_spin.setDecimals(4)
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
        self._label_changed()

    def _label_changed(self, *_args: Any) -> None:
        label = self.label_combo.currentData()
        if label is not None:
            self.length_spin.setValue(label.value)
            self.unit_combo.setCurrentText(label.unit)
        selected = label if label is not None else (self.all_labels[0] if self.all_labels else None)
        self.bars = rank_scale_bars(self.all_bars, selected, self.image.shape)
        self.bar_combo.blockSignals(True)
        self.bar_combo.clear()
        if self.bars:
            for index, bar in enumerate(self.bars):
                self.bar_combo.addItem(
                    f"{index + 1}: {bar.pixels:.1f} px  ·  y={(bar.y1 + bar.y2) / 2:.0f}  ·  信頼度 {bar.confidence:.0%}"
                )
            self.bar_combo.setCurrentIndex(0)
        else:
            self.bar_combo.addItem("候補なし（画像をクリックして指定）")
        self.bar_combo.blockSignals(False)
        self.canvas.set_candidates(self.all_labels, self.bars, 0 if self.bars else -1)
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
        self.mm_per_px = length_mm / pixels
        super().accept()
