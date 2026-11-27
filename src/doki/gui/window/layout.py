"""Main window layout and theme controls."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from doki.gui.helpers import (
    build_tsv_row,
    build_tsv_table,
)

if TYPE_CHECKING:
    from doki.gui.window.main import MainWindow


def _build_ui(self: MainWindow) -> None:
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
    self.result_copy_buttons = []
    for text, callback in (
        ("TSV行をコピー", lambda: self._copy_last_info(build_tsv_row)),
        ("見出し付きTSV行", lambda: self._copy_last_info(build_tsv_row, True)),
        ("縦テーブルをコピー", lambda: self._copy_last_info(build_tsv_table)),
        ("テキスト要約をコピー", self._copy_text_summary),
    ):
        button = QPushButton(text)
        button.setEnabled(False)
        button.clicked.connect(callback)
        action.addWidget(button)
        self.result_copy_buttons.append(button)
    outer.addLayout(action)
    self._update_scale_fields(self.scale_mode.currentText())


def _build_view_menu(self: MainWindow) -> None:
    menu = self.menuBar().addMenu("表示")
    theme_group = QActionGroup(self)
    app = QApplication.instance()
    current_theme = (
        app.property("pottery_theme_mode")
        if isinstance(app, QApplication)
        else None
    ) or "system"
    self.theme_actions = {}
    for theme, label in (
        ("system", "自動（システム設定）"),
        ("light", "ライト"),
        ("dark", "ダーク"),
    ):
        action = QAction(label, self)
        action.setCheckable(True)
        action.setChecked(current_theme == theme)
        action.triggered.connect(
            lambda _checked, selected=theme: self._set_theme(selected)
        )
        theme_group.addAction(action)
        menu.addAction(action)
        self.theme_actions[theme] = action
    self.dark_mode_action = self.theme_actions["dark"]
    menu.addSeparator()
    self.check_updates_action = QAction("更新を確認…", self)
    self.check_updates_action.triggered.connect(self.check_for_updates_manually)
    menu.addAction(self.check_updates_action)
    self.automatic_updates_action = QAction("起動時に更新を確認する", self)
    self.automatic_updates_action.setCheckable(True)
    self.automatic_updates_action.setChecked(
        bool(self._settings.value("check_updates_on_startup", True, type=bool))
    )
    self.automatic_updates_action.toggled.connect(
        lambda checked: self._settings.setValue("check_updates_on_startup", checked)
    )
    menu.addAction(self.automatic_updates_action)


def _set_theme(self: MainWindow, theme: str) -> None:
    from doki.gui.style import stylesheet_for_theme

    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return
    app.setProperty("pottery_theme_mode", theme)
    app.setStyleSheet(stylesheet_for_theme(theme, app))
    QSettings().setValue("theme_mode", theme)


def _path_row(self: MainWindow, edit: Any, callback: Any, kind: str) -> Any:
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
