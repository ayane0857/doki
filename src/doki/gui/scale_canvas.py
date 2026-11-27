"""Image canvas for interactive scale-bar measurement."""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from doki.scale.calibration import ScaleBarCandidate, ScaleTextCandidate


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
        self._rendered_source = (0, 0, 0, 0)
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
        if len(self.manual_points) == 1:
            return []
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
        visible_x0 = max(0, int(math.floor(-self.offset_x / self.scale)))
        visible_y0 = max(0, int(math.floor(-self.offset_y / self.scale)))
        visible_x1 = min(
            self.image_width,
            int(math.ceil((self.width() - self.offset_x) / self.scale)),
        )
        visible_y1 = min(
            self.image_height,
            int(math.ceil((self.height() - self.offset_y) / self.scale)),
        )
        if visible_x1 <= visible_x0 or visible_y1 <= visible_y0:
            visible_x0, visible_y0 = 0, 0
            visible_x1, visible_y1 = self.image_width, self.image_height
        source = (visible_x0, visible_y0, visible_x1 - visible_x0, visible_y1 - visible_y0)
        size = (
            max(1, round(source[2] * self.scale)),
            max(1, round(source[3] * self.scale)),
        )
        if source != self._rendered_source or size != self._rendered_size:
            source_pixmap = self.pixmap.copy(
                source[0], source[1], source[2], source[3]
            )
            self._rendered_pixmap = source_pixmap.scaled(
                *size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._rendered_source = source
            self._rendered_size = size
        return self._rendered_pixmap, source

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
        shown, source = self._scaled_image()
        source_x, source_y, _source_width, _source_height = source
        painter.drawPixmap(
            round(self.offset_x + source_x * self.scale),
            round(self.offset_y + source_y * self.scale),
            shown,
        )
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
