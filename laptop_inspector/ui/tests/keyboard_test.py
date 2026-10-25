"""Keyboard matrix test.

Every key gets pressed once. Qt receives a key event for anything the OS maps,
so a key that produces no event is genuinely dead - not a driver artefact.

Fn and the media row are excluded from the expected set: they are handled in
firmware and never reach an application, so counting them would produce false
failures on every machine.

Three things make this harder than it looks, all of them fixed here:

* **Left and right modifiers share one Qt key code.** `Key_Shift` is sent for
  both sides, so a matrix keyed on the Qt key lights up both shifts when you
  press one. The side is only available from the native virtual key
  (VK_LSHIFT / VK_RSHIFT), so each modifier is resolved by its own entry.
* **Tab never reaches `keyPressEvent`.** Qt consumes it for focus traversal
  before the widget sees it. It is intercepted in `event()` and in
  `focusNextPrevChild`.
* **Space looked untested because it had no label.** The row entry was `("", 6,
  "Space")`, so the press was recorded but the key could never paint as hit.
"""

from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from .. import theme

# Native virtual key codes. Qt collapses each pair into one key code, so these
# are the only way to tell which side was pressed.
VK_LSHIFT, VK_RSHIFT = 0xA0, 0xA1
VK_LCONTROL, VK_RCONTROL = 0xA2, 0xA3
VK_LMENU, VK_RMENU = 0xA4, 0xA5


class Key(NamedTuple):
    """One physical key. `ident` is unique per side, unlike the Qt key code."""

    label: str
    units: float
    qt: Optional[str] = None
    vk: Optional[int] = None
    side: str = ""

    @property
    def observable(self) -> bool:
        return self.qt is not None

    @property
    def ident(self) -> str:
        return f"{self.qt}|{self.vk or 0}"

    @property
    def name(self) -> str:
        """What gets reported when the key never registers."""
        return f"{self.side} {self.label}".strip() if self.side else self.label


def _row(*keys: Any) -> List[Key]:
    """Compact row builder: ("Q", 1) or ("Shift", 2.4, "Shift", VK_LSHIFT, "Left")."""
    out: List[Key] = []
    for item in keys:
        out.append(Key(*item))
    return out


ROWS: List[List[Key]] = [
    _row(("Esc", 1.2, "Escape"))
    + _row(*[(f"F{i}", 1, f"F{i}") for i in range(1, 13)])
    + _row(("Ins", 1, "Insert"), ("Del", 1, "Delete")),

    _row(("`", 1, "QuoteLeft"), ("1", 1, "1"), ("2", 1, "2"), ("3", 1, "3"),
         ("4", 1, "4"), ("5", 1, "5"), ("6", 1, "6"), ("7", 1, "7"),
         ("8", 1, "8"), ("9", 1, "9"), ("0", 1, "0"), ("-", 1, "Minus"),
         ("=", 1, "Equal"), ("Backspace", 2.2, "Backspace")),

    _row(("Tab", 1.6, "Tab"), ("Q", 1, "Q"), ("W", 1, "W"), ("E", 1, "E"),
         ("R", 1, "R"), ("T", 1, "T"), ("Y", 1, "Y"), ("U", 1, "U"),
         ("I", 1, "I"), ("O", 1, "O"), ("P", 1, "P"), ("[", 1, "BracketLeft"),
         ("]", 1, "BracketRight"), ("\\", 1.2, "Backslash")),

    _row(("Caps", 1.8, "CapsLock"), ("A", 1, "A"), ("S", 1, "S"), ("D", 1, "D"),
         ("F", 1, "F"), ("G", 1, "G"), ("H", 1, "H"), ("J", 1, "J"),
         ("K", 1, "K"), ("L", 1, "L"), (";", 1, "Semicolon"),
         ("'", 1, "Apostrophe"), ("Enter", 2.4, "Return")),

    _row(("Shift", 2.4, "Shift", VK_LSHIFT, "Left"), ("Z", 1, "Z"), ("X", 1, "X"),
         ("C", 1, "C"), ("V", 1, "V"), ("B", 1, "B"), ("N", 1, "N"),
         ("M", 1, "M"), (",", 1, "Comma"), (".", 1, "Period"), ("/", 1, "Slash"),
         ("Shift", 2.4, "Shift", VK_RSHIFT, "Right"), ("Up", 1, "Up")),

    _row(("Ctrl", 1.4, "Control", VK_LCONTROL, "Left"),
         ("Fn", 1, None),
         ("Alt", 1.2, "Alt", VK_LMENU, "Left"),
         ("Space", 6, "Space"),
         ("Alt", 1.2, "Alt", VK_RMENU, "Right"),
         ("Ctrl", 1.4, "Control", VK_RCONTROL, "Right"),
         ("Left", 1, "Left"), ("Down", 1, "Down"), ("Right", 1, "Right")),
]

TOTAL_UNITS = max(sum(k.units for k in row) for row in ROWS)
ALL_KEYS = [k for row in ROWS for k in row if k.observable]

# Qt key code -> candidates, so a press can be resolved without scanning 74 keys.
_BY_QT: Dict[int, List[Key]] = {}
for _key in ALL_KEYS:
    _code = getattr(Qt, f"Key_{_key.qt}", None)
    if _code is not None:
        _BY_QT.setdefault(int(_code), []).append(_key)


def _generic_modifier(vk: int) -> bool:
    """True when Windows handed us VK_SHIFT/VK_CONTROL/VK_MENU with no side."""
    return vk in (0, 0x10, 0x11, 0x12)


def _side_from_scan(scan: int) -> Optional[int]:
    """Fall back to the scan code when the virtual key has no side in it.

    Left Shift is 0x2A, right Shift 0x36. Left/right Ctrl and Alt share 0x1D /
    0x38, and the right-hand ones carry the E0 extended prefix - which Qt
    reports either as 0x100 in the high byte or as a full 0xE0xx value.
    """
    extended = bool(scan & 0x100) or (scan >> 8) == 0xE0
    low = scan & 0xFF
    if low == 0x2A:
        return VK_LSHIFT
    if low == 0x36:
        return VK_RSHIFT
    if low == 0x1D:
        return VK_RCONTROL if extended else VK_LCONTROL
    if low == 0x38:
        return VK_RMENU if extended else VK_LMENU
    return None


class KeyboardCanvas(QWidget):
    """The matrix itself. A plain widget - a QDialog cannot be embedded."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.pressed: List[str] = []
        self._pressed_set: set = set()
        self._last_seen: str = ""
        self.expected = [k.ident for k in ALL_KEYS]
        self.on_finish = None

    # ---- input
    def resolve(self, event) -> Optional[Key]:
        """Which physical key produced this event, side included."""
        candidates = _BY_QT.get(int(event.key())) or []
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        vk = int(event.nativeVirtualKey())
        if not _generic_modifier(vk):
            for key in candidates:
                if key.vk == vk:
                    return key

        # No side in the virtual key: ask the scan code.
        side = _side_from_scan(int(event.nativeScanCode()))
        for key in candidates:
            if key.vk and key.vk == side:
                return key
        # Still ambiguous (some remote/virtual keyboards). Take the left-hand
        # key rather than dropping the press.
        return candidates[0]

    def _record(self, event) -> bool:
        key = self.resolve(event)
        if key is None or key.ident in self._pressed_set:
            return False
        self._pressed_set.add(key.ident)
        self.pressed.append(key.name)
        self._last_seen = key.name
        self.update()
        return True

    def event(self, event) -> bool:  # noqa: N802
        # Three keys never reach keyPressEvent: Tab is consumed by focus
        # traversal, Space activates the focused button, and Esc is answered by
        # QDialog::keyPressEvent. All three are under test, so they are claimed
        # here before any of that runs.
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape and event.modifiers() & Qt.ShiftModifier:
                if self.on_finish:
                    self.on_finish()
                return True
            if event.key() in (Qt.Key_Tab, Qt.Key_Space, Qt.Key_Escape):
                self._record(event)
                return True
        return super().event(event)

    def focusNextPrevChild(self, forward: bool) -> bool:  # noqa: N802
        # Nothing to tab to, and Tab must stay a testable key.
        return False

    def keyPressEvent(self, event) -> None:  # noqa: N802
        # Esc is itself a key under test, so finishing needs Shift+Esc - which is
        # what the on-screen hint tells the buyer.
        if event.key() == Qt.Key_Escape and event.modifiers() & Qt.ShiftModifier:
            if self.on_finish:
                self.on_finish()
            return
        self._record(event)
        event.accept()

    def missing(self) -> List[str]:
        return [k.name for k in ALL_KEYS if k.ident not in self._pressed_set]

    # ---- paint
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor("#080B10"))

        margin = 28
        top = 78
        gap = 5
        unit = (w - 2 * margin - gap * (TOTAL_UNITS - 1)) / TOTAL_UNITS
        # Fill the canvas: a fixed height left a dead band under the matrix
        # on taller windows.
        key_h = min(62.0, (h - top - 18) / len(ROWS) - gap)

        title = QFont("Segoe UI", 15, QFont.DemiBold)
        painter.setFont(title)
        painter.setPen(QPen(QColor("#E7EEF7")))
        painter.drawText(QRectF(margin, 22, w - 2 * margin, 26), Qt.AlignLeft,
                         "Press every key once")

        sub = QFont("Segoe UI", 10)
        painter.setFont(sub)
        painter.setPen(QPen(QColor("#A9B7C7")))
        done = len(self._pressed_set)
        tail = f"last: {self._last_seen}" if self._last_seen else "nothing pressed yet"
        painter.drawText(
            QRectF(margin, 48, w - 2 * margin, 20), Qt.AlignLeft,
            f"{done} of {len(self.expected)} keys registered   ·   {tail}   ·   "
            f"Shift+Esc when finished")

        label_font = QFont("Segoe UI", 9, QFont.DemiBold)
        for r, row in enumerate(ROWS):
            x = margin
            y = top + r * (key_h + gap)
            for key in row:
                kw = key.units * unit + (key.units - 1) * gap
                hit = key.observable and key.ident in self._pressed_set
                rect = QRectF(x, y, kw, key_h)
                if hit:
                    painter.setBrush(QColor("#16351F"))
                    painter.setPen(QPen(QColor("#2ECC71"), 1.2))
                elif not key.observable:
                    painter.setBrush(QColor("#0D1218"))
                    painter.setPen(QPen(QColor("#1B232D"), 1.0))
                else:
                    painter.setBrush(QColor("#131A22"))
                    painter.setPen(QPen(QColor("#26303D"), 1.0))
                painter.drawRoundedRect(rect, 5, 5)

                painter.setFont(label_font)
                painter.setPen(QPen(QColor("#2ECC71") if hit
                                    else QColor("#3F4A58") if not key.observable
                                    else QColor("#9AA8B8")))
                painter.drawText(rect, Qt.AlignCenter, key.label)
                x += kw + gap

        painter.end()


class KeyboardTestDialog(QDialog):
    """Thin wrapper so the caller gets a dict back, like the screen test."""

    def __init__(self, parent: Optional[QDialog] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard test")
        self.resize(1000, 400)
        self.setStyleSheet(theme.STYLESHEET)
        self.result: Dict[str, Any] = {"run": False}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = KeyboardCanvas(self)
        layout.addWidget(self.canvas, 1)

        bar = QHBoxLayout()
        bar.setContentsMargins(28, 6, 28, 14)
        hint = QLabel("Left and right Shift/Ctrl/Alt are counted separately. "
                      "Fn and the media row are not testable from software.")
        hint.setStyleSheet("color:#8593A6; font-size: 14.5px;")
        finish = QPushButton("Finish and save")
        finish.setStyleSheet("background:#2563EB; color:white; font-weight:700;"
                             " padding:7px 16px; border-radius:5px;")
        finish.clicked.connect(self._save)
        bar.addWidget(hint)
        bar.addStretch(1)
        bar.addWidget(finish)
        layout.addLayout(bar)

        self.canvas.on_finish = self._save

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.canvas.setFocus()

    def _save(self) -> None:
        self.result = {
            "run": True,
            "pressed": list(self.canvas.pressed),
            "missing": self.canvas.missing(),
            "expected": len(self.canvas.expected),
        }
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self.result.get("run"):
            self.result = {"run": False}
        super().closeEvent(event)
