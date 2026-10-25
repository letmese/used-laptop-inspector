# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the bootable WinPE build.

    pyinstaller build_pe.spec --noconfirm

Produces dist_pe/UsedLaptopInspectorPE.exe - console, no Qt, no UAC, ~15 MB.

Differences from build.spec, and why:

  * **No PySide6 at all.** There is no GUI in WinPE, and bundling Qt would add
    30 MB to an image that has to fit in a RAM disk alongside the OS.
  * **console=True.** The operator has to read the result on a console.
  * **No UAC manifest.** WinPE runs as SYSTEM; a manifest that asks for
    elevation makes the process fail to start rather than prompt.
  * **No network features.** WinPE has no network stack until it is configured,
    so the market lookup and port photos are compiled out of the flow.
"""

import os
from pathlib import Path

ROOT = Path(SPECPATH).resolve()

datas = [
    (str(ROOT / "laptop_inspector" / "data" / "models.json"), "laptop_inspector/data"),
    (str(ROOT / "laptop_inspector" / "data" / "costs_pkr.json"), "laptop_inspector/data"),
    (str(ROOT / "laptop_inspector" / "data" / "port_layouts.json"), "laptop_inspector/data"),
]

hiddenimports = [
    "laptop_inspector.engine.checks.specs",
    "laptop_inspector.engine.checks.battery",
    "laptop_inspector.engine.checks.storage",
    "laptop_inspector.engine.checks.thermal",
    "laptop_inspector.engine.checks.gpu",
    "laptop_inspector.engine.checks.dgpu_presence",
    "laptop_inspector.engine.checks.peripherals",
]

# Qt is excluded wholesale. If anything in the engine ever starts importing it,
# this build fails loudly at analysis time instead of silently growing to 45 MB.
excludes = [
    "PySide6", "shiboken6", "PySide2", "PyQt5", "PyQt6",
    "tkinter", "unittest", "pydoc_data", "test",
]

a = Analysis(
    [str(ROOT / "pe_main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="UsedLaptopInspectorPE",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(ROOT / "build" / "version_info_pe.txt"),
)
