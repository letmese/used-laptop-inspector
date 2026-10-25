"""The Interactive Tests pane: the checks that need a human.

These are the tests no API can perform. They live in their own pane because they
are the only part of the tool that needs the buyer to do something, and mixing
them into the passive scan results would hide that.

Two groups: the three observation tests (screen, keyboard, ports) and the two
stress tests (CPU, GPU), which can be started on their own and watched live.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from .. import theme

TESTS = [
    ("screen", "🖥", "Screen",
     "Ten fullscreen patterns: flat colour, gradients, checkerboard and a 1px "
     "grid. Catches stuck pixels, backlight bleed and dead columns."),
    ("keyboard", "⌨", "Keyboard",
     "Press every key once on an on-screen matrix. Left and right modifiers "
     "count separately; any key that never registers is named."),
    ("ports", "🔌", "Ports & audio",
     "Finds photos of this exact model online, then walks the USB ports in "
     "order. Then a tone in each audio channel."),
]

STRESS = [
    ("cpu", "⚡", "CPU stress",
     "Loads every core and plots the real clock, utilisation and delivered "
     "work while it runs."),
    ("gpu", "◈", "GPU stress",
     "Drives D3D11 and watches for a driver reset, with the clear rate live."),
]


def _summary(key: str, result: Dict[str, Any]) -> tuple:
    """(text, badge style) for a completed test."""
    if not result.get("run"):
        return "Not run", "BadgeDark"

    if key == "screen":
        issues = result.get("issues") or []
        if issues:
            return f"{len(issues)} issue(s)", "BadgeAmber"
        return "No defects", "BadgeGreen"

    if key == "keyboard":
        missing = result.get("missing") or []
        pressed = len(result.get("pressed") or [])
        if missing:
            return f"{len(missing)} dead · {pressed} ok", "BadgeRed"
        return f"All {pressed} keys ok", "BadgeGreen"

    if key == "ports":
        failed = result.get("failed") or []
        audio = result.get("audio") or {}
        if failed:
            return f"{len(failed)} port(s) dead", "BadgeRed"
        if audio.get("run") and not (audio.get("left") and audio.get("right")):
            return "audio channel silent", "BadgeAmber"
        tested = result.get("ports_tested") or 0
        return (f"{tested} port(s) ok" if tested else "audio checked"), "BadgeGreen"

    return "done", "BadgeGreen"


def _stress_summary(key: str, data: Optional[Dict[str, Any]]) -> tuple:
    if not data:
        return "Not run", "BadgeDark"

    if key == "cpu":
        if not data.get("samples"):
            return "no samples", "BadgeRed"
        peak = data.get("peak_mhz") or 0
        sag = data.get("sag_ratio")
        if sag is None:
            return f"{peak:.0f} MHz", "BadgeGreen"
        style = "BadgeGreen" if sag >= 0.90 else "BadgeAmber" if sag >= 0.78 else "BadgeRed"
        return f"{peak:.0f} MHz · {sag * 100:.0f}% held", style

    if key == "gpu":
        if data.get("device_removed"):
            return "driver reset", "BadgeRed"
        if data.get("inconclusive"):
            return "inconclusive", "BadgeAmber"
        if not data.get("available"):
            return "unavailable", "BadgeDark"
        rate = data.get("frames_per_sec") or data.get("clears_per_sec") or 0
        if not rate:
            return "no rate recorded", "BadgeDark"
        return f"{rate:,} frames/s", "BadgeGreen"

    return "done", "BadgeGreen"


class InteractivePanel(QWidget):
    def __init__(self, results: Dict[str, Dict[str, Any]],
                 on_run: Callable[[str], None],
                 on_clear: Optional[Callable[[], None]] = None,
                 stress: Optional[Dict[str, Dict[str, Any]]] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._on_run = on_run
        self._results = results
        self._stress = stress or {}
        self._cards: Dict[str, tuple] = {}
        self._stress_cards: Dict[str, tuple] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        self.progress_lbl = QLabel("")
        self.progress_lbl.setObjectName("Mono")
        self.progress_lbl.setStyleSheet("font-size: 13px; color: #BCC8D6;")

        outer.addLayout(self._header("INTERACTIVE TESTS"))
        note = QLabel("The scan cannot see a stuck pixel or a dead key. These three "
                      "tests take about two minutes and feed straight into the "
                      "score and the counter-offer.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #BCC8D6; font-size: 14.5px;")
        outer.addWidget(note)

        row = QHBoxLayout()
        row.setSpacing(10)
        for key, icon, name, description in TESTS:
            row.addWidget(self._build_card(key, icon, name, description, 186), 1)
        outer.addLayout(row)

        if on_clear is not None:
            clear = QPushButton("Clear interactive results")
            clear.setObjectName("Ghost")
            clear.setFixedHeight(26)
            clear.clicked.connect(lambda: on_clear())
            outer.addWidget(clear, 0, Qt.AlignLeft)

        outer.addLayout(self._header("STRESS TESTS", show_progress=False))

        stress_row = QHBoxLayout()
        stress_row.setSpacing(10)
        for key, icon, name, description in STRESS:
            stress_row.addWidget(self._build_card(key, icon, name, description, 132,
                                                  stress_card=True), 1)
        outer.addLayout(stress_row)

        outer.addStretch(1)
        self.refresh()

    def _header(self, text: str, show_progress: bool = True) -> QHBoxLayout:
        head = QHBoxLayout()
        title = QLabel(text)
        title.setStyleSheet("font-size: 14.5px; font-weight: 800; color: #FFFFFF;"
                            " letter-spacing: 0.8px;")
        head.addWidget(title)
        head.addStretch(1)
        # A widget can only live in one layout; adding the same label twice
        # silently moves it to the second one.
        if show_progress:
            head.addWidget(self.progress_lbl)
        return head

    def _build_card(self, key: str, icon: str, name: str,
                    description: str, height: int, stress_card: bool = False) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        card.setFixedHeight(height)
        box = QVBoxLayout(card)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(6)

        top = QHBoxLayout()
        glyph = QLabel(icon)
        glyph.setStyleSheet("font-size: 21px;")
        top.addWidget(glyph)
        title = QLabel(name)
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #FFFFFF;")
        top.addWidget(title, 1)
        box.addLayout(top)

        body = QLabel(description)
        body.setWordWrap(True)
        body.setStyleSheet("color: #BCC8D6; font-size: 13.5px;")
        box.addWidget(body, 1)

        status = QLabel("Not run")
        status.setObjectName("BadgeDark")
        status.setAlignment(Qt.AlignCenter)
        status.setFixedHeight(20)
        box.addWidget(status, 0, Qt.AlignLeft)

        run = QPushButton("Run test")
        run.setFixedHeight(28)
        run.setStyleSheet("background:#2563EB; color:white; font-weight:700;"
                          " border-radius:4px; font-size: 14.5px;")
        run.clicked.connect(lambda _=False, k=key: self._on_run(k))
        box.addWidget(run)

        if stress_card:
            self._stress_cards[key] = (status, run)
        else:
            self._cards[key] = (status, run)
        return card

    def refresh(self) -> None:
        done = 0
        for key, (status, run) in self._cards.items():
            result = self._results.get(key) or {}
            text, style = _summary(key, result)
            self._set_badge(status, text, style)
            run.setText("Run again" if result.get("run") else "Run test")
            if result.get("run"):
                done += 1
        self.progress_lbl.setText(f"{done} of {len(self._cards)} run")

        for key, (status, run) in self._stress_cards.items():
            data = self._stress.get(key)
            text, style = _stress_summary(key, data)
            self._set_badge(status, text, style)
            run.setText("Run again" if data else "Run test")

    @staticmethod
    def _set_badge(label: QLabel, text: str, style: str) -> None:
        label.setText(text)
        if label.objectName() != style:
            label.setObjectName(style)
            label.style().unpolish(label)
            label.style().polish(label)

    def set_results(self, results: Dict[str, Dict[str, Any]]) -> None:
        self._results = results
        self.refresh()

    def set_stress(self, stress: Dict[str, Dict[str, Any]]) -> None:
        self._stress = stress
        self.refresh()
