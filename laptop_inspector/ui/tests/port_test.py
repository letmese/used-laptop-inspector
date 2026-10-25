"""USB port and audio channel test.

USB: the dialog looks the machine up in `data/port_layouts.json`, draws its port
layout from above, and walks the testable ports one at a time in physical order.
The current port is highlighted and named, so "port 3" becomes "USB 2.0, left
side, second from the front".

Detection is `RegisterDeviceNotification` on `GUID_DEVINTERFACE_USB_DEVICE`, so
any USB device counts - a mouse, a stick, a phone - and the arrival arrives as a
window message rather than a poll. The older code listened for volume arrivals,
which only ever fired for USB *storage* and therefore looked broken with
anything else.

Audio: a tone is played hard-left and then hard-right. One channel silent means
the jack, the speaker or the codec, not the driver - which is exactly the kind of
thing a seller says "it's just the driver, bhai".
"""

from __future__ import annotations

import ctypes
import io
import math
import re
import struct
import time
import wave
from ctypes import wintypes
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QAbstractNativeEventFilter, Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFrame,
                               QHBoxLayout, QLabel, QPushButton, QVBoxLayout)

from ...engine import webimages
from .. import theme
from .photo_panel import PhotoBand
from .port_map import Layout, Port, lookup

WM_DEVICECHANGE = 0x0219
DBT_DEVICEARRIVAL = 0x8000
DBT_DEVICEREMOVECOMPLETE = 0x8004
DBT_DEVTYP_DEVICEINTERFACE = 0x00000005
DEVICE_NOTIFY_WINDOW_HANDLE = 0x00000000


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


# {A5DCBF10-6530-11D2-901F-00C04FB951ED}
GUID_DEVINTERFACE_USB_DEVICE = GUID(
    0xA5DCBF10, 0x6530, 0x11D2,
    (ctypes.c_ubyte * 8)(0x90, 0x1F, 0x00, 0xC0, 0x4F, 0xB9, 0x51, 0xED))


class DEV_BROADCAST_DEVICEINTERFACE(ctypes.Structure):
    _fields_ = [("dbcc_size", wintypes.DWORD),
                ("dbcc_devicetype", wintypes.DWORD),
                ("dbcc_reserved", wintypes.DWORD),
                ("dbcc_classguid", GUID),
                ("dbcc_name", ctypes.c_wchar * 1)]


class DEV_BROADCAST_HDR(ctypes.Structure):
    _fields_ = [("dbcv_size", wintypes.DWORD),
                ("dbcv_devicetype", wintypes.DWORD),
                ("dbcv_reserved", wintypes.DWORD)]


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD), ("pt", wintypes.POINT)]


user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterDeviceNotificationW.restype = wintypes.HANDLE
user32.RegisterDeviceNotificationW.argtypes = [wintypes.HWND, ctypes.c_void_p,
                                               wintypes.DWORD]
user32.UnregisterDeviceNotification.argtypes = [wintypes.HANDLE]

_VID_PID = re.compile(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})")


def _describe(path: str) -> str:
    """A USB device path, made readable."""
    match = _VID_PID.search(path or "")
    if match:
        return f"USB device VID {match.group(1).upper()} / PID {match.group(2).upper()}"
    return "USB device"


def _device_key(path: str) -> str:
    """Identity of the physical device, so its several interfaces count once."""
    parts = [p for p in (path or "").split("#") if p]
    return "#".join(parts[1:3]) if len(parts) >= 3 else path


class DeviceWatcher(QAbstractNativeEventFilter):
    """USB device arrivals, filtered to device interfaces.

    Volume arrivals are deliberately ignored: they only fire for storage, which
    is why the previous version appeared to do nothing when a mouse was plugged
    in.
    """

    def __init__(self, on_arrival, on_removal=None) -> None:
        super().__init__()
        self.on_arrival = on_arrival
        self.on_removal = on_removal
        self.arrivals = 0
        self.last_path = ""
        self._seen: Dict[str, float] = {}
        self._last_time = 0.0

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
        except Exception:
            return False, 0
        if msg.message != WM_DEVICECHANGE:
            return False, 0
        event = int(msg.wParam)
        if event not in (DBT_DEVICEARRIVAL, DBT_DEVICEREMOVECOMPLETE):
            return False, 0
        try:
            header = ctypes.cast(int(msg.lParam),
                                 ctypes.POINTER(DEV_BROADCAST_HDR)).contents
        except Exception:
            return False, 0
        if header.dbcv_devicetype != DBT_DEVTYP_DEVICEINTERFACE:
            return False, 0

        # dbcc_name is a wchar[1] at the end of the structure.
        offset = DEV_BROADCAST_DEVICEINTERFACE.dbcc_name.offset
        try:
            path = ctypes.wstring_at(int(msg.lParam) + offset) or ""
        except Exception:
            path = ""

        if event == DBT_DEVICEREMOVECOMPLETE:
            if self.on_removal:
                self.on_removal(_describe(path))
            return False, 0

        key = _device_key(path)
        now = time.monotonic()
        # One physical device announces several interfaces. Count it once, and
        # never twice within a couple of seconds.
        if self._seen.get(key, 0.0) > now - 4.0 or now - self._last_time < 1.0:
            return False, 0
        self._seen[key] = now
        self._last_time = now
        self.arrivals += 1
        self.last_path = path
        self.on_arrival(_describe(path))
        return False, 0


def _tone_wav(freq: int = 880, ms: int = 700, channel: str = "left",
              rate: int = 44100) -> bytes:
    """A 2-channel WAV with the tone panned hard to one side."""
    count = int(rate * ms / 1000)
    frames = bytearray()
    for i in range(count):
        # fade in/out so the tone does not click
        env = min(1.0, i / (rate * 0.02), (count - i) / (rate * 0.02))
        value = int(11000 * env * math.sin(2 * math.pi * freq * i / rate))
        left = value if channel in ("left", "both") else 0
        right = value if channel in ("right", "both") else 0
        frames += struct.pack("<hh", left, right)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))
    return buffer.getvalue()


def play_tone(channel: str) -> bool:
    try:
        import winsound
        data = _tone_wav(channel=channel)
        winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_ASYNC)
        return True
    except Exception:
        return False


class PortTestDialog(QDialog):
    def __init__(self, machine: Optional[Dict[str, Any]] = None,
                 parent: Optional[QDialog] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ports & audio")
        self.resize(940, 900)
        self.setStyleSheet(theme.STYLESHEET)

        self.machine = machine or {}
        self.layout: Layout = lookup(self.machine)
        self.order: List[Port] = self.layout.testable

        self.result: Dict[str, Any] = {"run": False}
        self.failed: List[str] = []
        self.skipped: List[str] = []
        self.tested = 0
        self._index = 0
        self._done = False
        self._notify = None
        self._watcher: Optional[DeviceWatcher] = None
        self._searched = False

        self._build()
        self._render_current()

    # ---------------------------------------------------------------- build
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("Ports & audio")
        title.setStyleSheet("font-size: 23.5px; font-weight:700;")
        head.addWidget(title)
        head.addStretch(1)
        self.model_lbl = QLabel(self.layout.family)
        self.model_lbl.setObjectName("BadgeDark")
        self.model_lbl.setStyleSheet("font-size: 14.5px; font-weight:700;"
                                     " padding:3px 9px;")
        head.addWidget(self.model_lbl)
        layout.addLayout(head)

        if self.layout.known:
            hint_text = (f"{self.layout.family}: photos of that machine's port "
                         "edges are fetched below as you go. The same chassis "
                         "shipped with different options - skip any port this "
                         "unit does not have.")
        else:
            hint_text = ("This model is not in the port map, so the port order may "
                         "not match. The photos are still of this machine - test "
                         "the ports it actually has and skip the rest.")
        hint = QLabel(hint_text)
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#BCC8D6; font-size: 15px;")
        layout.addWidget(hint)

        # The photos are the picture. A drawn strip of the ports was tried and
        # removed: it was my interpretation of the layout, and a photograph of
        # the actual machine beats an interpretation every time.
        self.photos = PhotoBand()
        layout.addWidget(self.photos, 1)

        if self.layout.source:
            source = QLabel(f"Port order: {self.layout.source}")
            source.setWordWrap(True)
            source.setStyleSheet("color:#8593A6; font-size: 13px;")
            layout.addWidget(source)

        step = QFrame()
        step.setObjectName("Card")
        box = QVBoxLayout(step)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(4)

        self.step_lbl = QLabel("")
        self.step_lbl.setStyleSheet("font-size: 18px; font-weight:700;")
        box.addWidget(self.step_lbl)

        self.detect_lbl = QLabel("")
        self.detect_lbl.setWordWrap(True)
        self.detect_lbl.setStyleSheet("color:#BCC8D6; font-size: 15px;")
        box.addWidget(self.detect_lbl)

        row = QHBoxLayout()
        self.dead_btn = QPushButton("Mark this port dead")
        self.dead_btn.setObjectName("Ghost")
        self.dead_btn.clicked.connect(self._mark_dead)
        self.skip_btn = QPushButton("Skip")
        self.skip_btn.setObjectName("Ghost")
        self.skip_btn.clicked.connect(self._skip)
        row.addWidget(self.dead_btn)
        row.addWidget(self.skip_btn)
        row.addStretch(1)
        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("Mono")
        self.count_lbl.setStyleSheet("font-size: 13.5px; color:#BCC8D6;")
        row.addWidget(self.count_lbl)
        box.addLayout(row)
        layout.addWidget(step)

        audio = QFrame()
        audio.setObjectName("Card")
        ab = QVBoxLayout(audio)
        ab.setContentsMargins(16, 12, 16, 12)
        ab.setSpacing(6)

        ab.addWidget(QLabel("Audio channels — headphones, one side at a time"))
        abtn = QHBoxLayout()
        left = QPushButton("Play left")
        left.setObjectName("Ghost")
        left.clicked.connect(lambda: self._play("left"))
        right = QPushButton("Play right")
        right.setObjectName("Ghost")
        right.clicked.connect(lambda: self._play("right"))
        abtn.addWidget(left)
        abtn.addWidget(right)
        abtn.addStretch(1)
        ab.addLayout(abtn)

        self.heard_left = QCheckBox("I heard the tone in the left ear")
        self.heard_right = QCheckBox("I heard the tone in the right ear")
        for box_ in (self.heard_left, self.heard_right):
            box_.setStyleSheet("font-size: 15.5px;")
            ab.addWidget(box_)
        self.audio_note = QLabel("")
        self.audio_note.setStyleSheet("color:#F59E0B; font-size: 14.5px;")
        ab.addWidget(self.audio_note)
        layout.addWidget(audio)

        finish = QPushButton("Finish and save")
        finish.setStyleSheet("background:#2563EB; color:white; font-weight:700;"
                             " padding:9px 18px; border-radius:5px;")
        finish.clicked.connect(self._save)
        layout.addWidget(finish)

    # ------------------------------------------------------------ lifecycle
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._notify:
            return
        try:
            hwnd = int(self.winId())
            filt = DEV_BROADCAST_DEVICEINTERFACE()
            filt.dbcc_size = ctypes.sizeof(DEV_BROADCAST_DEVICEINTERFACE)
            filt.dbcc_devicetype = DBT_DEVTYP_DEVICEINTERFACE
            filt.dbcc_classguid = GUID_DEVINTERFACE_USB_DEVICE
            self._notify = user32.RegisterDeviceNotificationW(
                hwnd, ctypes.byref(filt), DEVICE_NOTIFY_WINDOW_HANDLE)
        except Exception as exc:
            self.detect_lbl.setText(f"USB notifications unavailable: {exc}")

        self._watcher = DeviceWatcher(self._on_arrival, self._on_removal)
        QApplication.instance().installNativeEventFilter(self._watcher)

        if not self._searched:
            self._searched = True
            self.photos.set_model(self._photo_query())

    def closeEvent(self, event) -> None:  # noqa: N802
        self._teardown()
        if not self.result.get("run"):
            self.result = {"run": False}
        super().closeEvent(event)

    def _teardown(self) -> None:
        try:
            self.photos.teardown()
        except Exception:
            pass
        if self._watcher is not None:
            try:
                QApplication.instance().removeNativeEventFilter(self._watcher)
            except Exception:
                pass
            self._watcher = None
        if self._notify:
            try:
                user32.UnregisterDeviceNotification(self._notify)
            except Exception:
                pass
            self._notify = None

    def _photo_query(self) -> str:
        return webimages.model_query(self.machine, self.layout.family)

    # ------------------------------------------------------------- stepping
    def _render_current(self) -> None:
        total = len(self.order)
        self.count_lbl.setText(f"{self.tested} ok · {len(self.failed)} dead · "
                               f"{len(self.skipped)} skipped")

        if self._index >= total:
            self._done = True
            self.step_lbl.setText("All testable ports covered")
            self.detect_lbl.setText(
                "Nothing left to plug in. Finish to save, or use Skip if a port "
                "is still highlighted.")
            self.dead_btn.setEnabled(False)
            self.skip_btn.setEnabled(False)
            return

        port = self.order[self._index]
        position = port.index + 1
        side_ports = [p for p in self.layout.ports if p.side == port.side]
        total_side = len(side_ports)
        where = (f"{port.where}, {position} of {total_side} from the back"
                 if port.side in ("left", "right") else "rear edge")
        self.step_lbl.setText(f"{self._index + 1} of {total}  ·  {port.label}")
        self.detect_lbl.setText(
            f"Plug a USB device in — {where}. Any USB device works: a mouse, a "
            "stick, a phone. Windows reports it here the moment it enumerates.")
        self.dead_btn.setEnabled(True)
        self.skip_btn.setEnabled(True)
        self.photos.prefer_side(port.side)

    def _advance(self) -> None:
        self._index += 1
        self._render_current()

    def _on_arrival(self, description: str) -> None:
        if self._done or self._index >= len(self.order):
            return
        port = self.order[self._index]
        port.status = "ok"
        self.tested += 1
        self.detect_lbl.setText(f"✓ {description} on {port.label} ({port.where})")
        self.detect_lbl.setStyleSheet("color:#2ECC71; font-size: 15px;")
        self._advance()
        self.detect_lbl.setStyleSheet("color:#BCC8D6; font-size: 15px;")

    def _on_removal(self, description: str) -> None:
        if not self._done:
            self.detect_lbl.setText(f"{description} removed — plug it into the "
                                    "next port.")

    def _mark_dead(self) -> None:
        if self._index >= len(self.order):
            return
        port = self.order[self._index]
        port.status = "dead"
        self.failed.append(f"{port.label} ({port.where})")
        self._advance()

    def _skip(self) -> None:
        if self._index >= len(self.order):
            return
        port = self.order[self._index]
        port.status = "skipped"
        self.skipped.append(port.label)
        self._advance()

    # ---------------------------------------------------------------- audio
    def _play(self, channel: str) -> None:
        if not play_tone(channel):
            self.audio_note.setText("Could not play audio on this machine.")
            return
        self.audio_note.setText(f"Playing {channel} channel…")

    # --------------------------------------------------------------- result
    def _save(self) -> None:
        audio_ran = self.heard_left.isChecked() or self.heard_right.isChecked()
        self.result = {
            "run": True,
            "ports_tested": self.tested,
            "failed": list(self.failed),
            "skipped": list(self.skipped),
            "layout_family": self.layout.family,
            "layout_known": self.layout.known,
            "audio": {
                "run": audio_ran,
                "left": self.heard_left.isChecked(),
                "right": self.heard_right.isChecked(),
            },
        }
        self._teardown()
        self.accept()
