# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec.

    pyinstaller build.spec --noconfirm

Produces dist/UsedLaptopInspector.exe - a single file, no console, no installer.
The same exe runs headless with `UsedLaptopInspector.exe --cli ...`, which is the
path that will run from WinPE later.

Deliberately not bundled:
  * smartmontools (GPL) - we talk to the drive through DeviceIoControl instead
  * Sysinternals - Microsoft's licence does not permit redistribution
  * any VC++ redistributable beyond what PySide6 already needs
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

block_cipher = None
ROOT = Path(SPECPATH).resolve()

# Set ULI_NO_UAC=1 to build a variant that does not ask for elevation. Only
# useful for smoke-testing the packaging; the shipping build wants the prompt,
# because without admin the storage check silently comes back empty.
REQUEST_ADMIN = os.environ.get("ULI_NO_UAC") != "1"

datas = [
    (str(ROOT / "laptop_inspector" / "data" / "models.json"), "laptop_inspector/data"),
    (str(ROOT / "laptop_inspector" / "data" / "costs_pkr.json"), "laptop_inspector/data"),
    (str(ROOT / "laptop_inspector" / "data" / "port_layouts.json"), "laptop_inspector/data"),
    (str(ROOT / "assets" / "icon.ico"), "assets"),
    (str(ROOT / "assets" / "icon.png"), "assets"),
]

# Qt modules we actually use. Everything else is excluded to keep the exe small -
# this has to build and run on a 2011 quad-core with 12 GB of RAM.
hiddenimports = [
    "laptop_inspector.engine.checks.specs",
    "laptop_inspector.engine.checks.battery",
    "laptop_inspector.engine.checks.storage",
    "laptop_inspector.engine.checks.thermal",
    "laptop_inspector.engine.checks.gpu",
    "laptop_inspector.engine.checks.dgpu_presence",
    "laptop_inspector.engine.checks.interactive",
    # v2 dialogs are imported lazily inside handlers; name them so the analysis
    # cannot miss them.
    "laptop_inspector.ui.tests.panel",
    "laptop_inspector.ui.tests.screen_test",
    "laptop_inspector.ui.tests.keyboard_test",
    "laptop_inspector.ui.tests.port_test",
    "laptop_inspector.ui.tests.port_map",
    "laptop_inspector.ui.tests.stress_lab",
    "laptop_inspector.ui.tests.photo_panel",
    "laptop_inspector.engine.webimages",
]

excludes = [
    "tkinter", "unittest", "pydoc", "doctest", "test", "sqlite3",
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtPositioning", "PySide6.QtSerialPort", "PySide6.QtSensors",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtXml", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtSvg", "PySide6.QtSvgWidgets",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech", "PySide6.QtWebSockets", "PySide6.QtHttpServer",
    "PySide6.QtGraphs", "PySide6.QtGraphsWidgets", "PySide6.QtConcurrent",
]

# PyInstaller's PySide6 hook copies Qt DLLs and data files regardless of the
# `excludes` list above - that list only stops Python modules being imported.
# A Widgets app still shipped Qt6Qml, Qt6Quick, Qt6Pdf, the 20 MB software
# OpenGL fallback and 198 translation files, which is dead weight that has to be
# unpacked from the onefile bundle on every launch.
DROP_BINARIES = (
    "opengl32sw.dll",          # software GL fallback; a Widgets app never asks
    "qt6qml.dll", "qt6quick.dll", "qt6quick3d", "qt6quickshapes",
    "qt6pdf.dll", "qt6designer.dll", "qt6shadertools.dll",
    "qt6virtualkeyboard", "qt6labs", "qt6network.dll", "qt6sql.dll",
)
DROP_DATA_DIRS = (
    "pyside6/translations/",
    "plugins/qmltooling/", "plugins/assetimporters/", "plugins/sceneparsers/",
    "plugins/renderers/", "plugins/multimedia/", "plugins/sqldrivers/",
    "plugins/designer/", "plugins/canbus/", "plugins/tls/",
)
# Only the image formats the app actually opens: its own icon, and the JPEG
# photos of laptop ports.
KEEP_IMAGE_FORMATS = ("qico", "qpng", "qjpeg", "qgif")

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

def _slim(entries):
    """Drop the Qt payload this app never touches, and report what it saved."""
    kept, dropped, saved = [], 0, 0
    for entry in entries:
        name = entry[0].replace("\\", "/").lower()
        base = name.rsplit("/", 1)[-1]
        drop = any(token in name for token in DROP_BINARIES)
        drop = drop or any(token in name for token in DROP_DATA_DIRS)
        if "imageformats/" in name and not any(k in base for k in KEEP_IMAGE_FORMATS):
            drop = True
        if drop:
            dropped += 1
            try:
                saved += os.path.getsize(entry[1])
            except OSError:
                pass
            continue
        kept.append(entry)
    return kept, dropped, saved


if os.environ.get("ULI_NO_SLIM") == "1":
    # Kept so the trimmed build can be measured against the untrimmed one.
    print("[slim] disabled by ULI_NO_SLIM")
else:
    a.binaries, _nb, _sb = _slim(a.binaries)
    a.datas, _nd, _sd = _slim(a.datas)
    print(f"[slim] dropped {_nb + _nd} files, {(_sb + _sd) / 1048576:.1f} MB of payload")

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="UsedLaptopInspector",
    # Without a version resource the exe has no publisher, no product name and
    # no version in Properties, which is exactly what SmartScreen shows you.
    version=str(ROOT / "build" / "version_info.txt"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # The app needs admin for SMART. Embedding the manifest means Windows asks
    # once at launch instead of the scan silently coming back empty.
    uac_admin=REQUEST_ADMIN,
    icon=str(ROOT / "assets" / "icon.ico"),
)
