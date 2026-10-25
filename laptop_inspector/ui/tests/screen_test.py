"""Fullscreen pixel and uniformity test.

A stuck pixel, a bright spot, a pressure mark or backlight bleed is invisible in
a screenshot and invisible to any API. The only way to find it is to fill the
panel with flat colour and look. So this does exactly that, in the order that
exposes different faults:

    white / black   -> stuck pixels, dust under the panel
    RGB / grey      -> dead subpixels, colour cast
    gradient        -> banding, 6-bit panels
    checkerboard    -> single stuck pixels
    1px grid        -> dead columns and rows

The buyer advances with a click or Space, exits with Esc, and then answers one
question about what they saw.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QDialog, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from .. import theme

# (name, kind, argument)
STEPS = [
    ("White", "solid", "#FFFFFF"),
    ("Black", "solid", "#000000"),
    ("Red", "solid", "#FF0000"),
    ("Green", "solid", "#00FF00"),
    ("Blue", "solid", "#0000FF"),
    ("Mid grey", "solid", "#808080"),
    ("Dark grey", "solid", "#1A1A1A"),
    ("Gradient", "gradient", None),
    ("Checkerboard", "checker", 8),
    ("1px grid", "grid", 1),
]

ISSUES = [
    ("stuck pixel(s)", "Bright or dark dots that never change colour"),
    ("backlight bleed", "Light leaking at the edges, visible on black"),
    ("uneven brightness", "Patches brighter or dimmer than the rest"),
    ("colour banding", "Visible steps in the gradient instead of a smooth ramp"),
    ("line or dead zone", "A vertical or horizontal stripe that never changes"),
]


class ScreenCanvas(QWidget):
    """Paints one test pattern. No chrome, no cursor, no distractions."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.BlankCursor)
        self._step = 0
        self.finished = False
        self.on_advance = None

    def set_step(self, index: int) -> None:
        self._step = max(0, min(len(STEPS) - 1, index))
        self.update()

    @property
    def step_index(self) -> int:
        return self._step

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.advance()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Space, Qt.Key_Right, Qt.Key_Down, Qt.Key_Return):
            self.advance()
        elif event.key() in (Qt.Key_Escape, Qt.Key_Q):
            if self.on_advance:
                self.on_advance(done=True)
        else:
            super().keyPressEvent(event)

    def advance(self) -> None:
        if self._step + 1 >= len(STEPS):
            if self.on_advance:
                self.on_advance(done=True)
            return
        self.set_step(self._step + 1)
        if self.on_advance:
            self.on_advance(done=False)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        w, h = self.width(), self.height()
        name, kind, arg = STEPS[self._step]

        if kind == "solid":
            painter.fillRect(0, 0, w, h, QColor(arg))
        elif kind == "gradient":
            grad = QLinearGradient(0, 0, w, 0)
            for i in range(33):
                grad.setColorAt(i / 32.0, QColor(i * 8, i * 8, i * 8))
            painter.fillRect(0, 0, w, h, grad)
        elif kind == "checker":
            size = max(4, arg)
            painter.fillRect(0, 0, w, h, QColor("#000000"))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#FFFFFF"))
            for y in range(0, h, size):
                for x in range(0, w, size):
                    if ((x // size) + (y // size)) % 2 == 0:
                        painter.drawRect(x, y, size, size)
        elif kind == "grid":
            painter.fillRect(0, 0, w, h, QColor("#FFFFFF"))
            painter.setPen(QPen(QColor("#000000"), arg))
            for x in range(0, w, 8):
                painter.drawLine(x, 0, x, h)
            for y in range(0, h, 8):
                painter.drawLine(0, y, w, y)

        # Faint hint so the buyer knows how to leave
        painter.setPen(QPen(QColor(255, 255, 255, 70) if kind == "solid"
                            and STEPS[self._step][2] == "#FFFFFF"
                            else QColor(128, 128, 128, 90)))
        font = QFont("Segoe UI", 9)
        painter.setFont(font)
        painter.drawText(QRectF(0, h - 26, w - 16, 20),
                         Qt.AlignRight | Qt.AlignVCenter,
                         f"{name}  ·  {self._step + 1}/{len(STEPS)}  ·  "
                         f"click or Space for next  ·  Esc to finish")
        painter.end()


class ScreenTestDialog(QDialog):
    """Runs the pattern sequence, then asks what the buyer saw."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Screen test")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setCursor(Qt.BlankCursor)

        self.result: Dict[str, Any] = {"run": False, "issues": []}
        self._checks: Dict[str, QCheckBox] = {}
        self._started = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = ScreenCanvas(self)
        self.canvas.on_advance = self._on_advance
        layout.addWidget(self.canvas)

    def start(self) -> None:
        import time
        self._started = time.time()
        self.canvas.set_step(0)
        self.showFullScreen()
        self.activateWindow()
        self.canvas.setFocus()

    def _on_advance(self, done: bool) -> None:
        if done:
            self._ask()

    def _ask(self) -> None:
        self.showNormal()
        self.setCursor(Qt.ArrowCursor)
        self.canvas.setCursor(Qt.ArrowCursor)

        panel = QWidget(self)
        panel.setObjectName("ScreenAsk")
        panel.setStyleSheet(
            theme.STYLESHEET +
            "QWidget#ScreenAsk { background-color: #0F141B; }"
            "QCheckBox { font-size: 17px; padding: 7px 0; }"
            "QCheckBox::indicator { width: 20px; height: 20px; border-radius: 5px;"
            " border: 1px solid #2E3B4A; background: #080B10; }"
            "QCheckBox::indicator:checked { background: #2563EB;"
            " border-color: #2563EB; }")
        panel.setGeometry(self.rect())
        panel.setAttribute(Qt.WA_StyledBackground, True)
        box = QVBoxLayout(panel)
        box.setContentsMargins(48, 40, 48, 32)
        box.setSpacing(10)

        title = QLabel("What did you see?")
        title.setStyleSheet("font-size: 26px; font-weight:700;")
        box.addWidget(title)

        hint = QLabel("Tick anything you spotted during the pattern sequence. "
                      "Leave everything unticked if the panel looked clean.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#BCC8D6; font-size: 15.5px;")
        box.addWidget(hint)
        box.addSpacing(8)

        for key, description in ISSUES:
            check = QCheckBox(f"{key}   —   {description}")
            check.setStyleSheet("font-size: 16px; padding:4px 0;")
            self._checks[key] = check
            box.addWidget(check)

        box.addStretch(1)

        buttons = QWidget()
        from PySide6.QtWidgets import QHBoxLayout
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        again = QPushButton("Run again")
        again.clicked.connect(self._restart)
        done = QPushButton("Save result")
        done.setObjectName("Primary")
        done.setStyleSheet("background:#2563EB; color:white; font-weight:700;"
                           " padding:8px 18px; border-radius:5px;")
        done.clicked.connect(self._save)
        row.addWidget(again)
        row.addStretch(1)
        row.addWidget(done)
        box.addWidget(buttons)

        self._panel = panel
        panel.show()
        panel.raise_()

    def _restart(self) -> None:
        if hasattr(self, "_panel"):
            self._panel.deleteLater()
        self.canvas.set_step(0)
        self.showFullScreen()
        self.canvas.setFocus()

    def _save(self) -> None:
        import time
        issues = [k for k, c in self._checks.items() if c.isChecked()]
        screen = self.screen() or (self.parent().screen() if self.parent() else None)
        geometry = screen.geometry() if screen else None
        self.result = {
            "run": True,
            "issues": issues,
            "resolution": f"{geometry.width()}x{geometry.height()}" if geometry else "?",
            "refresh_hz": screen.refreshRate() if screen else None,
            "seconds": round(time.time() - self._started, 1) if self._started else None,
            "patterns_shown": len(STEPS),
        }
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self.result.get("run"):
            self.result = {"run": False, "issues": []}
        super().closeEvent(event)
