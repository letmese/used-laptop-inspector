"""Verify the keyboard matrix against real Windows key messages.

QTest.keyClick builds a synthetic QKeyEvent with no native key info, so it
cannot tell left Shift from right Shift. SendInput goes through the real
message loop, so Qt's key mapper fills in nativeVirtualKey/nativeScanCode the
same way it would for a human. That is the only way to prove the side
detection works before shipping it.
"""

import ctypes
import sys
import time
from ctypes import wintypes

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, ".")

from laptop_inspector.ui.tests.keyboard_test import KeyboardTestDialog

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
INPUT_KEYBOARD = 1


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_ubyte * 32)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _U)]


user32 = ctypes.WinDLL("user32", use_last_error=True)


def send(scan, flags=0, up=False):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    # SendInput will not translate scan code 0x01 to VK_ESCAPE on its own, so Esc
    # has to be injected as a virtual key. Real hardware is unaffected.
    if scan == 0x01:
        inp.ki = KEYBDINPUT(0x1B, 0, (KEYEVENTF_KEYUP if up else 0), 0, None)
    else:
        inp.ki = KEYBDINPUT(0, scan, flags | (KEYEVENTF_KEYUP if up else 0), 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def tap(scan, flags=0, hold=0.05):
    send(scan, flags)
    time.sleep(hold)
    send(scan, flags, up=True)
    time.sleep(0.08)


# (name, scan code, flags) - scan codes are what the hardware sends
KEYS = [
    ("LShift", 0x2A, KEYEVENTF_SCANCODE),
    ("RShift", 0x36, KEYEVENTF_SCANCODE),
    ("LCtrl", 0x1D, KEYEVENTF_SCANCODE),
    ("RCtrl", 0x1D, KEYEVENTF_SCANCODE | KEYEVENTF_EXTENDEDKEY),
    ("LAlt", 0x38, KEYEVENTF_SCANCODE),
    ("RAlt", 0x38, KEYEVENTF_SCANCODE | KEYEVENTF_EXTENDEDKEY),
    ("Tab", 0x0F, KEYEVENTF_SCANCODE),
    ("Space", 0x39, KEYEVENTF_SCANCODE),
    ("A", 0x1E, KEYEVENTF_SCANCODE),
    ("Esc", 0x01, KEYEVENTF_SCANCODE),
]

app = QApplication(sys.argv)
dialog = KeyboardTestDialog()
dialog.move(80, 80)
dialog.show()
dialog.raise_()
dialog.activateWindow()
app.processEvents()

if not dialog.isActiveWindow():
    print("SKIP: window did not take focus, refusing to send keys elsewhere")
    sys.exit(2)

canvas = dialog.canvas
canvas.setFocus()
app.processEvents()

# Raw event probe: record what Qt actually reports for each key.
seen = []
original = canvas.keyPressEvent


def probe(event):
    seen.append((event.key(), int(event.nativeVirtualKey()),
                 int(event.nativeScanCode()), canvas.resolve(event)))
    original(event)


canvas.keyPressEvent = probe

for name, scan, flags in KEYS:
    tap(scan, flags)
    # SendInput posts to the message queue; the event for key N is often
    # delivered after key N+1 is injected. Drain properly between keys.
    for _ in range(6):
        app.processEvents()
        time.sleep(0.02)

for _ in range(12):
    app.processEvents()
    time.sleep(0.02)

print("\n--- raw Qt key data ---")
for code, vk, sc, key in seen:
    print(f"  key=0x{code:04X} vk=0x{vk:02X} scan=0x{sc:03X} -> "
          f"{key.name if key else None}")

print("\n--- recorded ---")
print("pressed:", canvas.pressed)
print("count:", len(canvas.pressed), "of", len(canvas.expected))
missing = canvas.missing()
print("missing:", len(missing))
print("  first 12:", missing[:12])

want = {"Left Shift", "Right Shift", "Left Ctrl", "Right Ctrl",
        "Left Alt", "Right Alt", "Tab", "Space", "A", "Esc"}
got = set(canvas.pressed)
print("\nrequired keys present:", sorted(want - got) or "ALL OK")
print("extra:", sorted(got - want))

dialog.close()
