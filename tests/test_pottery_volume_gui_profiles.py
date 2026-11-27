from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pottery_volume_core import Profiles
from pottery_volume_gui_profiles import ProfileEditorDialog


def test_rotation_axis_can_be_dragged_and_undone(qt_app: QApplication) -> None:
    image = np.full((100, 100), 255, dtype=np.uint8)
    y_px = np.arange(20.0, 81.0)
    profiles = Profiles(
        y_px=y_px,
        r_in_px=np.full(len(y_px), 8.0),
        r_out_px=np.full(len(y_px), 20.0),
        top_y_px=20.0,
        bottom_y_px=80.0,
        liquid_y_px=20.0,
    )
    dialog = ProfileEditorDialog(profiles, image, 30.0, None)
    dialog.show()
    qt_app.processEvents()

    canvas = dialog.canvas
    axis_screen_x = canvas.offset_x + (canvas.axis_x - canvas.crop_x) * canvas.scale
    start = QPoint(round(axis_screen_x), 0)
    end = QPoint(start.x() + 10, start.y())
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)

    assert dialog.axis_x == pytest.approx(40.0)
    assert dialog.undo_button.isEnabled()
    dialog._undo()
    assert dialog.axis_x == pytest.approx(30.0)
    assert canvas.axis_x == pytest.approx(30.0)
    dialog.close()


def test_control_point_hit_takes_priority_over_rotation_axis(qt_app: QApplication) -> None:
    image = np.full((100, 100), 255, dtype=np.uint8)
    y_px = np.arange(20.0, 81.0)
    profiles = Profiles(
        y_px=y_px,
        r_in_px=np.full(len(y_px), 8.0),
        r_out_px=np.full(len(y_px), 20.0),
        top_y_px=20.0,
        bottom_y_px=80.0,
        liquid_y_px=20.0,
    )
    dialog = ProfileEditorDialog(profiles, image, 30.0, None)
    dialog.show()
    qt_app.processEvents()

    canvas = dialog.canvas
    canvas.scale = 1.0
    point = canvas._screen(8.0, 50.0, 1.0)
    axis_screen_x = canvas.offset_x + (canvas.axis_x - canvas.crop_x) * canvas.scale
    assert abs(point.x() - axis_screen_x) <= 10

    QTest.mousePress(
        canvas, Qt.MouseButton.LeftButton, pos=QPoint(round(point.x()), round(point.y()))
    )

    assert canvas.active_point is not None
    assert not canvas._dragging_axis
    QTest.mouseRelease(
        canvas, Qt.MouseButton.LeftButton, pos=QPoint(round(point.x()), round(point.y()))
    )
    dialog.close()


def test_add_mode_accepts_points_near_rotation_axis(qt_app: QApplication) -> None:
    image = np.full((100, 100), 255, dtype=np.uint8)
    y_px = np.arange(20.0, 81.0)
    profiles = Profiles(
        y_px=y_px,
        r_in_px=np.full(len(y_px), 8.0),
        r_out_px=np.full(len(y_px), 20.0),
        top_y_px=20.0,
        bottom_y_px=80.0,
        liquid_y_px=20.0,
    )
    dialog = ProfileEditorDialog(profiles, image, 30.0, None)
    dialog.show()
    qt_app.processEvents()

    canvas = dialog.canvas
    canvas.scale = 1.0
    canvas.set_add_mode(True, True)
    added: list[tuple[float, float, bool]] = []
    canvas.on_add_point = lambda y, radius, inner: added.append((y, radius, inner))
    point = canvas._screen(5.0, 50.0, 1.0)

    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=QPoint(round(point.x()), round(point.y()))
    )

    assert added == [(50.0, 5.0, True)]
    assert not canvas._dragging_axis
    dialog.close()


def test_auto_profile_button_replaces_edits_and_can_be_undone(
    qt_app: QApplication,
) -> None:
    image = np.full((100, 100), 255, dtype=np.uint8)
    y_px = np.arange(20.0, 81.0)
    profiles = Profiles(
        y_px=y_px,
        r_in_px=np.full(len(y_px), 8.0),
        r_out_px=np.full(len(y_px), 20.0),
        top_y_px=20.0,
        bottom_y_px=80.0,
        liquid_y_px=20.0,
    )
    generated_axes: list[float] = []

    def generate(axis_x: float) -> Profiles:
        generated_axes.append(axis_x)
        return Profiles(
            y_px=y_px,
            r_in_px=np.full(len(y_px), 6.0),
            r_out_px=np.full(len(y_px), 18.0),
            top_y_px=20.0,
            bottom_y_px=80.0,
            liquid_y_px=20.0,
        )

    dialog = ProfileEditorDialog(
        profiles,
        image,
        30.0,
        None,
        auto_profile_generator=generate,
    )
    dialog.table.item(0, 1).setText("10.00")
    assert dialog.edited_inner_indices

    dialog.auto_profile_button.click()

    assert generated_axes == [30.0]
    assert dialog.baseline_inner[0] == pytest.approx(6.0)
    assert dialog.inner_values[0] == pytest.approx(6.0)
    assert not dialog.edited_inner_indices
    dialog._undo()
    assert dialog.baseline_inner[0] == pytest.approx(8.0)
    assert dialog.inner_values[0] == pytest.approx(10.0)
    dialog.close()
