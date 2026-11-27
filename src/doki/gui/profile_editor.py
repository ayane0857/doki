"""Manual contour editing dialog and public canvas import."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from doki.analysis.core import Profiles, apply_profile_overrides
from doki.gui.profile_canvas import ProfileCanvas as ProfileCanvas
from doki.gui.profile_editor_history import ProfileEditorHistory

_MAX_CONTROL_POINTS = 240  # Upper bound on manually added control points per canvas.


class ProfileEditorDialog(QDialog):
    def __init__(
        self,
        profiles: Profiles,
        image: np.ndarray,
        axis_x: float,
        parent: Any,
        min_component_area: int = 5,
        adaptive_threshold: bool = False,
        original_image: np.ndarray | None = None,
        auto_profile_generator: Callable[[float], Profiles] | None = None,
    ) -> None:
        """
        ``min_component_area`` と ``adaptive_threshold`` は「ノイズ除去後の画像を表示」
        ボタンで使う（省略時は既定値 5 / 通常の二値化）。
        """
        super().__init__(parent)
        self.setWindowTitle("断面輪郭を画像上で手動補正")
        self.resize(1180, 720)
        self.axis_x = float(axis_x)
        self.auto_profile_generator = auto_profile_generator
        self._load_profiles(profiles)
        self._history = ProfileEditorHistory(self)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "既存点をドラッグして調整できます。「点を追加」を押し、画像の左右どちらかを複数回クリックすると、"
                "指定した高さに補正点を追加できます。点の間は補間して再計算します。"
                "白い破線の回転軸もドラッグして移動できます。"
                "Ctrl+マウスホイールで拡大・縮小、ホイールを押しながらドラッグで画像を移動、"
                "Ctrl+Z で直前の操作を元に戻せます。"
            )
        )
        point_controls = QHBoxLayout()
        self.surface_combo = QComboBox()
        self.surface_combo.addItem("内面輪郭を追加", True)
        self.surface_combo.addItem("外面輪郭を追加", False)
        self.add_points_button = QPushButton("点を追加")
        self.add_points_button.setCheckable(True)
        self.undo_button = QPushButton("元に戻す (Ctrl+Z)")
        self.undo_button.setEnabled(False)
        self.denoise_button = QPushButton("ノイズ除去後の画像を表示")
        self.denoise_button.setCheckable(True)
        self.denoise_button.setToolTip(
            "二値化して小さなノイズを除去した画像を表示します（表示のみで、計算結果には影響しません）。"
        )
        self.auto_profile_button = QPushButton("自動輪郭を生成")
        self.auto_profile_button.setEnabled(auto_profile_generator is not None)
        self.auto_profile_button.setToolTip(
            "現在の回転軸で解析時の断面から輪郭を再抽出し、手動補正を置き換えます。"
        )
        point_controls.addWidget(QLabel("追加する輪郭:"))
        point_controls.addWidget(self.surface_combo)
        point_controls.addWidget(self.add_points_button)
        point_controls.addWidget(self.undo_button)
        point_controls.addWidget(self.denoise_button)
        point_controls.addWidget(self.auto_profile_button)
        point_controls.addWidget(QLabel("クリックした位置から軸までの距離を輪郭半径にします。"), 1)
        layout.addLayout(point_controls)
        body = QHBoxLayout()
        self.canvas = ProfileCanvas(
            original_image if original_image is not None else image,
            profiles,
            axis_x,
            self.sample_y,
            self.inner_values,
            self.outer_values,
            min_component_area=min_component_area,
            adaptive_threshold=adaptive_threshold,
        )
        self.canvas.on_drag = self._canvas_changed
        self.canvas.on_drag_end = self._commit
        self.canvas.on_axis_drag = self._axis_changed
        self.canvas.on_axis_drag_end = self._commit
        self.canvas.on_add_point = self._add_control_point
        body.addWidget(self.canvas, 1)
        self.table = QTableWidget(len(self.sample_y), 3)
        self.table.setMinimumWidth(340)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setHorizontalHeaderLabels(["画像 y", "内面半径", "外面半径"])
        self.table.verticalHeader().setDefaultSectionSize(23)
        self._populate_table()
        self.table.cellChanged.connect(self._table_changed)
        body.addWidget(self.table)
        layout.addLayout(body, 1)
        self.add_points_button.toggled.connect(self._toggle_add_points)
        self.undo_button.clicked.connect(self._undo)
        self.denoise_button.toggled.connect(self._toggle_denoised)
        self.auto_profile_button.clicked.connect(self._generate_automatic_profiles)
        self.surface_combo.currentIndexChanged.connect(self._surface_changed)
        # セル編集中は QLineEdit 側の Ctrl+Z（文字入力の取り消し）が優先される
        self._undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self._undo_shortcut.activated.connect(self._undo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("補正して再計算")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("キャンセル")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _commit(self) -> None:
        self._history.commit(self)
        self.undo_button.setEnabled(self._history.can_undo)

    def _undo(self) -> None:
        if self.canvas.active_point is not None or self.canvas._dragging_axis:
            return
        if self._history.undo(self):
            self.canvas.set_axis_x(self.axis_x)
            self._refresh_profiles()
            self.undo_button.setEnabled(self._history.can_undo)

    # ---- 画像表示 ----

    def _toggle_denoised(self, enabled: bool) -> None:
        self.denoise_button.setText(
            "ノイズ除去前の画像に戻す" if enabled else "ノイズ除去後の画像を表示"
        )
        self.canvas.set_show_denoised(enabled)

    def _generate_automatic_profiles(self) -> None:
        if self.auto_profile_generator is None:
            return
        try:
            profiles = self.auto_profile_generator(self.axis_x)
        except ValueError as exc:
            QMessageBox.warning(self, "自動輪郭を生成できません", str(exc))
            return
        self._load_profiles(profiles)
        self._refresh_profiles()
        self._commit()

    def _load_profiles(self, profiles: Profiles) -> None:
        self.corrected_profiles = profiles
        self.baseline_y = profiles.y_px.copy()
        self.baseline_inner = profiles.r_in_px.copy()
        self.baseline_outer = profiles.r_out_px.copy()
        sample_indices = np.unique(
            np.linspace(0, len(profiles.y_px) - 1, min(40, len(profiles.y_px))).round().astype(int)
        )
        self.sample_y = profiles.y_px[sample_indices]
        self.inner_values = profiles.r_in_px[sample_indices].copy()
        self.outer_values = profiles.r_out_px[sample_indices].copy()
        self.original_inner_values = self.inner_values.copy()
        self.original_outer_values = self.outer_values.copy()
        self.edited_inner_indices: set[int] = set()
        self.edited_outer_indices: set[int] = set()

    def _refresh_profiles(self) -> None:
        self.canvas.y_min = float(self.corrected_profiles.top_y_px)
        self.canvas.y_max = float(self.corrected_profiles.bottom_y_px)
        self.canvas.set_profiles(self.sample_y, self.inner_values, self.outer_values)
        self._populate_table()

    def _table_values(self) -> tuple[np.ndarray, np.ndarray]:
        inner_values: list[float] = []
        outer_values: list[float] = []
        for row in range(self.table.rowCount()):
            inner_item = self.table.item(row, 1)
            outer_item = self.table.item(row, 2)
            if inner_item is None or outer_item is None:
                raise ValueError("輪郭の入力欄を確認してください。")
            inner_values.append(float(inner_item.text()))
            outer_values.append(float(outer_item.text()))
        inner = np.asarray(inner_values)
        outer = np.asarray(outer_values)
        return inner, outer

    def _populate_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.sample_y))
        for row, (y, inner, outer) in enumerate(
            zip(self.sample_y, self.inner_values, self.outer_values, strict=False)
        ):
            values = (y, inner, outer)
            for column, value in enumerate(values):
                item = QTableWidgetItem(f"{value:.2f}")
                if column == 0:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)

    def _toggle_add_points(self, enabled: bool) -> None:
        self.add_points_button.setText("点の追加を終了" if enabled else "点を追加")
        self._surface_changed()

    def _surface_changed(self, *_args: Any) -> None:
        self.canvas.set_add_mode(
            self.add_points_button.isChecked(),
            bool(self.surface_combo.currentData()),
        )

    def _add_control_point(self, y: float, radius: float, is_inner: bool) -> None:
        if len(self.sample_y) >= _MAX_CONTROL_POINTS:
            QMessageBox.information(
                self,
                "点数の上限",
                f"手動補正点は{_MAX_CONTROL_POINTS}点まで追加できます。",
            )
            return
        nearest = int(np.argmin(np.abs(self.sample_y - y)))
        if abs(float(self.sample_y[nearest]) - y) < 0.75:
            index = nearest
        else:
            index = int(np.searchsorted(self.sample_y, y))
            new_y = np.insert(self.sample_y, index, y)
            self.inner_values = np.insert(
                self.inner_values,
                index,
                np.interp(y, self.sample_y, self.inner_values),
            )
            self.outer_values = np.insert(
                self.outer_values,
                index,
                np.interp(y, self.sample_y, self.outer_values),
            )
            baseline_inner_at_y = float(np.interp(y, self.baseline_y, self.baseline_inner))
            baseline_outer_at_y = float(np.interp(y, self.baseline_y, self.baseline_outer))
            self.original_inner_values = np.insert(
                self.original_inner_values, index, baseline_inner_at_y
            )
            self.original_outer_values = np.insert(
                self.original_outer_values, index, baseline_outer_at_y
            )
            self.sample_y = new_y
            # 挿入で後ろへずれた「編集済み」インデックスを補正する
            self.edited_inner_indices = {
                i + 1 if i >= index else i for i in self.edited_inner_indices
            }
            self.edited_outer_indices = {
                i + 1 if i >= index else i for i in self.edited_outer_indices
            }
        if is_inner:
            self.inner_values[index] = min(radius, self.outer_values[index] - 0.25)
            self.edited_inner_indices.add(index)
        else:
            self.outer_values[index] = max(radius, self.inner_values[index] + 0.25)
            self.edited_outer_indices.add(index)
        self._populate_table()
        self.canvas.set_profiles(self.sample_y, self.inner_values, self.outer_values)
        self._commit()

    def _table_changed(self, _row: int, _column: int) -> None:
        try:
            inner, outer = self._table_values()
        except ValueError, AttributeError:
            return
        if not np.all(np.isfinite(inner)) or not np.all(np.isfinite(outer)):
            return
        if np.any(inner < 0) or np.any(outer <= inner):
            return
        if _column == 1:
            self.edited_inner_indices.update(
                index
                for index, (before, after) in enumerate(
                    zip(self.original_inner_values, inner, strict=False)
                )
                if before != after
            )
        if _column == 2:
            self.edited_outer_indices.update(
                index
                for index, (before, after) in enumerate(
                    zip(self.original_outer_values, outer, strict=False)
                )
                if before != after
            )
        self.inner_values, self.outer_values = inner, outer
        self.canvas.set_profiles(self.sample_y, inner, outer)
        self._commit()

    def _canvas_changed(self, inner: np.ndarray, outer: np.ndarray) -> None:
        self.edited_inner_indices.update(
            index
            for index, (before, after) in enumerate(
                zip(self.original_inner_values, inner, strict=False)
            )
            if before != after
        )
        self.edited_outer_indices.update(
            index
            for index, (before, after) in enumerate(
                zip(self.original_outer_values, outer, strict=False)
            )
            if before != after
        )
        self.table.blockSignals(True)
        for row, (inner_value, outer_value) in enumerate(zip(inner, outer, strict=False)):
            inner_item = self.table.item(row, 1)
            outer_item = self.table.item(row, 2)
            if inner_item is not None:
                inner_item.setText(f"{inner_value:.2f}")
            if outer_item is not None:
                outer_item.setText(f"{outer_value:.2f}")
        self.table.blockSignals(False)
        self.inner_values, self.outer_values = inner, outer

    def _axis_changed(self, axis_x: float) -> None:
        self.axis_x = axis_x

    def accept(self) -> None:
        try:
            inner, outer = self._table_values()
            if not np.all(np.isfinite(inner)) or not np.all(np.isfinite(outer)):
                raise ValueError("半径は有限の数値で入力してください。")
            if np.any(inner < 0) or np.any(outer <= inner):
                raise ValueError("外面半径は内面半径より大きくしてください。")
            y_px = self.baseline_y

            def apply_deltas(
                baseline: np.ndarray,
                edited_indices: set[int],
                control_values: np.ndarray,
                original_control_values: np.ndarray,
            ) -> np.ndarray:
                if not edited_indices:
                    return baseline.copy()
                edit_indices = sorted(edited_indices)
                edit_y = self.sample_y[edit_indices]
                edit_delta = control_values[edit_indices] - original_control_values[edit_indices]
                delta = np.interp(
                    y_px,
                    edit_y,
                    edit_delta,
                    left=edit_delta[0],
                    right=edit_delta[-1],
                )
                corrected = baseline + delta
                return np.where(corrected < 0, 0.0, corrected)

            corrected_inner = apply_deltas(
                self.baseline_inner,
                self.edited_inner_indices,
                inner,
                self.original_inner_values,
            )
            corrected_outer = apply_deltas(
                self.baseline_outer,
                self.edited_outer_indices,
                outer,
                self.original_outer_values,
            )
            self.corrected_profiles = apply_profile_overrides(
                self.corrected_profiles,
                corrected_inner,
                corrected_outer,
                ["断面プロファイルを手動補正しました。"],
            )
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "入力を確認してください", str(exc))
            return
        super().accept()
