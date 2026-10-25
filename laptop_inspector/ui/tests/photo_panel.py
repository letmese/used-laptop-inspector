"""Photographs of the machine under test, fetched from the web while it runs.

The drawn strip tells you the order; a photo tells you what you are looking at.
So the port test shows both: the model is detected, the web is searched for
pictures of that exact machine, and the best ones are shown next to the port
being tested.

Nothing here blocks the test. The search runs on its own thread, failures are
silent, and every result is cached so a second run works with no network at all.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ...engine import webimages
from .. import theme

PREVIEW_H = 260


class PhotoWorker(QObject):
    """Search and download off the UI thread."""

    done = Signal(list, list)      # list[dict], list[bytes]
    failed = Signal(str)

    def __init__(self, model: str) -> None:
        super().__init__()
        self.model = model

    @Slot()
    def run(self) -> None:
        try:
            photos = webimages.search(self.model)
            meta: List[Dict[str, Any]] = []
            blobs: List[bytes] = []
            for photo in photos:
                data = webimages.download(photo)
                if data:
                    # credit/host/side are properties, so they are not in
                    # __dict__ - build the record explicitly.
                    meta.append({
                        "url": photo.url, "page": photo.page,
                        "title": photo.title, "licence": photo.licence,
                        "author": photo.author, "provider": photo.provider,
                        "host": photo.host, "credit": photo.credit(),
                        "side": photo.side,
                    })
                    blobs.append(data)
            self.done.emit(meta, blobs)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class PhotoViewer(QDialog):
    """Full-size view of one photo, with its credit."""

    def __init__(self, pixmap: QPixmap, caption: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Port photo")
        self.setStyleSheet(theme.STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        label = QLabel()
        screen = self.screen().availableGeometry() if self.screen() else None
        limit_w = int(screen.width() * 0.86) if screen else 1200
        limit_h = int(screen.height() * 0.80) if screen else 800
        label.setPixmap(pixmap.scaled(limit_w, limit_h, Qt.KeepAspectRatio,
                                      Qt.SmoothTransformation))
        layout.addWidget(label)

        note = QLabel(caption)
        note.setWordWrap(True)
        note.setStyleSheet("color:#A9B7C7; font-size: 13.5px;")
        layout.addWidget(note)
        self.resize(label.pixmap().width() + 24, label.pixmap().height() + 70)


class PhotoBand(QFrame):
    """Search button, preview, credit line and paging."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self._meta: List[Dict[str, Any]] = []
        self._pixmaps: List[QPixmap] = []
        self._index = 0
        self._thread: Optional[QThread] = None
        self._worker: Optional[PhotoWorker] = None
        self._wanted_side = ""

        box = QVBoxLayout(self)
        box.setContentsMargins(14, 10, 14, 10)
        box.setSpacing(6)

        head = QHBoxLayout()
        title = QLabel("PHOTOS OF THIS MACHINE")
        title.setStyleSheet("font-size: 12.5px; font-weight:800; color:#BCC8D6;"
                            " letter-spacing:0.8px;")
        head.addWidget(title)
        head.addStretch(1)

        self.status = QLabel("not searched yet")
        self.status.setObjectName("Mono")
        self.status.setStyleSheet("font-size: 13px; color:#8593A6;")
        head.addWidget(self.status)

        self.prev_btn = QPushButton("‹")
        self.prev_btn.setObjectName("Ghost")
        self.prev_btn.setFixedSize(30, 30)
        self.prev_btn.clicked.connect(lambda: self._step(-1))
        self.next_btn = QPushButton("›")
        self.next_btn.setObjectName("Ghost")
        self.next_btn.setFixedSize(30, 30)
        self.next_btn.clicked.connect(lambda: self._step(1))
        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("Mono")
        self.count_lbl.setStyleSheet("font-size: 13px; color:#BCC8D6;")
        for widget in (self.prev_btn, self.count_lbl, self.next_btn):
            widget.setVisible(False)
            head.addWidget(widget)

        self.find_btn = QPushButton("Find photos")
        self.find_btn.setObjectName("Ghost")
        self.find_btn.setFixedHeight(30)
        self.find_btn.setMinimumWidth(112)
        self.find_btn.clicked.connect(self.search)
        head.addWidget(self.find_btn)
        box.addLayout(head)

        self.preview = QLabel("No photo yet — press Find photos to search the web "
                              "for this model.")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setFixedHeight(PREVIEW_H)
        self.preview.setStyleSheet("color:#8593A6; font-size: 14.5px;"
                                   " background:#0B0F15; border-radius:6px;")
        self.preview.mousePressEvent = self._open_viewer  # type: ignore[assignment]
        box.addWidget(self.preview)

        self.caption = QLabel("")
        self.caption.setWordWrap(True)
        self.caption.setStyleSheet("color:#93A1B4; font-size: 12.5px;")
        box.addWidget(self.caption)

    # ---- searching
    def search(self, model: str = "") -> None:
        if self._thread is not None:
            return
        if not model:
            model = self._model
        if not model:
            self.status.setText("no model detected")
            return

        self.status.setText("searching the web…")
        self.find_btn.setEnabled(False)
        self._thread = QThread(self)
        self._worker = PhotoWorker(model)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    _model = ""

    def set_model(self, model: str, auto: bool = True) -> None:
        self._model = model or ""
        if not self._model:
            self.status.setText("model not identified")
            self.caption.setText(
                "This machine did not report a model name, so there is nothing "
                "specific to search for. The port name and position above still "
                "apply.")
            return
        if auto:
            self.search(self._model)

    @Slot(list, list)
    def _on_done(self, meta: List[Dict[str, Any]], blobs: List[bytes]) -> None:
        self._stop_thread()
        self._meta = []
        self._pixmaps = []
        for item, blob in zip(meta, blobs):
            pixmap = QPixmap()
            if pixmap.loadFromData(blob) and pixmap.width() > 200:
                self._meta.append(item)
                self._pixmaps.append(pixmap)

        if not self._pixmaps:
            self.status.setText("nothing found")
            self.caption.setText(
                "No usable photo for this model. The port name and position "
                "above are still correct.")
            self.find_btn.setEnabled(True)
            return

        self.status.setText(f"{len(self._pixmaps)} found")
        for widget in (self.prev_btn, self.count_lbl, self.next_btn):
            widget.setVisible(len(self._pixmaps) > 1)
        self.find_btn.setText("Refresh")
        self.find_btn.setEnabled(True)
        self._index = self._best_index()
        # Let the layout settle before scaling: on the first run the dialog is
        # still being sized, and rendering into a zero-width label produced a
        # thumbnail instead of the preview.
        QTimer.singleShot(0, self._render)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._stop_thread()
        self.status.setText("search failed")
        self.caption.setText(message)
        self.find_btn.setEnabled(True)

    def _stop_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
            self._thread = None
            self._worker = None

    # ---- display
    def prefer_side(self, side: str) -> None:
        """Show the photo that matches the side being tested, if there is one."""
        self._wanted_side = side
        if not self._pixmaps:
            return
        best = self._best_index()
        if best != self._index:
            self._index = best
            self._render()

    def _best_index(self) -> int:
        """The photo most likely to show a port edge of the side under test.

        A photo that names the side wins; otherwise a long thin image wins,
        because a side-on shot of a laptop edge is a strip, while a hero shot is
        roughly 4:3. Picking "the first result" gave a different picture run to
        run and sometimes picked a lid shot.
        """
        if not self._pixmaps:
            return 0

        def rank(index: int):
            item = self._meta[index]
            pixmap = self._pixmaps[index]
            ratio = pixmap.width() / max(1, pixmap.height())
            named = 1 if (self._wanted_side and item.get("side") == self._wanted_side) else 0
            strip = 1 if ratio >= 2.2 else 0
            return (named, strip, round(ratio, 2), pixmap.width())

        return max(range(len(self._pixmaps)), key=rank)

    def _step(self, delta: int) -> None:
        if not self._pixmaps:
            return
        self._index = (self._index + delta) % len(self._pixmaps)
        self._render()

    def _render(self) -> None:
        if not self._pixmaps:
            return
        pixmap = self._pixmaps[self._index]
        width = max(320, self.preview.width())
        self.preview.setPixmap(pixmap.scaled(width, PREVIEW_H,
                                             Qt.KeepAspectRatio,
                                             Qt.SmoothTransformation))
        self.preview.setStyleSheet("background:#0B0F15; border-radius:6px;")
        self.count_lbl.setText(f"{self._index + 1} / {len(self._pixmaps)}")

        item = self._meta[self._index]
        bits = []
        if item.get("title"):
            bits.append(item["title"][:70])
        credit = item.get("credit") or item.get("licence") or item.get("host") or ""
        if credit:
            bits.append(credit)
        side = item.get("side")
        if side:
            bits.insert(0, f"{side} side")
        bits.append("reference photo — not annotated")
        self.caption.setText("  ·  ".join(bits))

    def _open_viewer(self, event) -> None:
        if not self._pixmaps:
            return
        caption = self.caption.text()
        viewer = PhotoViewer(self._pixmaps[self._index], caption, self)
        viewer.exec()

    def teardown(self) -> None:
        self._stop_thread()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._pixmaps:
            self._render()
