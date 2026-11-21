# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

datas = [
    ('THIRD_PARTY_LICENSES.txt', '.'),
    ('docs/gui/README.txt', '.'),
    ('BUILD_INFO.json', '.'),
]
binaries = []
hiddenimports = []
tmp_ret = collect_all('rapidocr')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
unused_qt_modules = (
    'PySide6.Qt3D',
    'PySide6.QtBluetooth',
    'PySide6.QtCharts',
    'PySide6.QtDataVisualization',
    'PySide6.QtLocation',
    'PySide6.QtMultimedia',
    'PySide6.QtNetworkAuth',
    'PySide6.QtPdf',
    'PySide6.QtPdfWidgets',
    'PySide6.QtPositioning',
    'PySide6.QtQml',
    'PySide6.QtQuick',
    'PySide6.QtRemoteObjects',
    'PySide6.QtScxml',
    'PySide6.QtSensors',
    'PySide6.QtSerialBus',
    'PySide6.QtSerialPort',
    'PySide6.QtSpatialAudio',
    'PySide6.QtSpeech',
    'PySide6.QtTextToSpeech',
    'PySide6.QtVirtualKeyboard',
    'PySide6.QtWebChannel',
    'PySide6.QtWebEngine',
    'PySide6.QtWebSockets',
)
tmp_ret = collect_all(
    'PySide6',
    filter_submodules=lambda name: not name.startswith(unused_qt_modules),
)
unused_qt_names = tuple(name.removeprefix('PySide6.') for name in unused_qt_modules)
unused_qt_binary_prefixes = tuple(
    prefix
    for name in unused_qt_names
    for prefix in (name, 'Qt6' + name.removeprefix('Qt'))
)
qt_datas = [
    item for item in tmp_ret[0]
    if not any(name in item[0] or name in item[1] for name in unused_qt_names)
    and '\\qml\\' not in item[0].lower()
    and '/qml/' not in item[0].lower()
]
qt_binaries = [
    item for item in tmp_ret[1]
    if not Path(item[0]).name.startswith(unused_qt_binary_prefixes)
]
datas += qt_datas; binaries += qt_binaries; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('shapely')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['pottery_volume_gui.pyw'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', *unused_qt_modules],
    noarchive=False,
    optimize=0,
)

# Qt's PyInstaller hook may add every available plugin after collect_all filters
# have run. Remove unused Qt modules from the final TOC after confirming the GUI
# imports only QtCore, QtGui, and QtWidgets.
unused_qt_path_tokens = tuple(
    token.lower()
    for name in unused_qt_names
    for token in (name, "Qt6" + name.removeprefix("Qt"))
)


def is_unused_qt_item(item):
    path = f"{item[0]}/{item[1]}".replace("\\", "/").lower()
    return (
        any(token in path for token in unused_qt_path_tokens)
        or "/pyside6/qml/" in path
        or "/pyside6/qt/qml/" in path
    )


a.binaries = [item for item in a.binaries if not is_unused_qt_item(item)]
a.datas = [item for item in a.datas if not is_unused_qt_item(item)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PotteryVolume_gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='PotteryVolume_gui',
)
