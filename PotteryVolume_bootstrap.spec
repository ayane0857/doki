# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['pottery_volume_bootstrap.py'],
    pathex=[],
    binaries=[],
    datas=[('BOOTSTRAP_VERSION', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'PySide6', 'numpy', 'opencv', 'scipy', 'matplotlib', 'rapidocr'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PotteryVolume_bootstrap',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
