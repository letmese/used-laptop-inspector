"""Builds assets/icon.ico from vector drawing.

Generated rather than illustrated so it stays sharp at 16 px in a taskbar and at
256 px in Explorer. Run directly to regenerate:

    python -m laptop_inspector.ui.icon
"""

from __future__ import annotations

import os
import struct
import sys

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QGuiApplication, QImage, QLinearGradient,
                           QPainter, QPainterPath, QPen)

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]

INK_TOP = QColor("#1b2735")
INK_BOTTOM = QColor("#0a0e14")
SHIELD = QColor("#e8eef7")
ACCENT = QColor("#ffb02e")
ACCENT_DEEP = QColor("#f08c00")


def _shield_path(rect: QRectF) -> QPainterPath:
    """A shield: flat shoulders, tapering to a rounded point."""
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    path = QPainterPath()
    path.moveTo(x + w * 0.5, y)
    path.lineTo(x + w, y + h * 0.18)
    path.lineTo(x + w, y + h * 0.55)
    path.cubicTo(x + w, y + h * 0.82, x + w * 0.74, y + h * 0.96,
                 x + w * 0.5, y + h)
    path.cubicTo(x + w * 0.26, y + h * 0.96, x, y + h * 0.82,
                 x, y + h * 0.55)
    path.lineTo(x, y + h * 0.18)
    path.closeSubpath()
    return path


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

    s = float(size)
    pad = s * 0.055
    body = QRectF(pad, pad, s - 2 * pad, s - 2 * pad)

    # ---- rounded square base with a vertical gradient
    gradient = QLinearGradient(0, body.top(), 0, body.bottom())
    gradient.setColorAt(0.0, INK_TOP)
    gradient.setColorAt(1.0, INK_BOTTOM)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(gradient))
    painter.drawRoundedRect(body, s * 0.22, s * 0.22)

    # ---- hairline inner border for definition on light backgrounds
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(QColor(255, 255, 255, 26), max(1.0, s * 0.008)))
    painter.drawRoundedRect(body.adjusted(s * 0.006, s * 0.006,
                                          -s * 0.006, -s * 0.006),
                            s * 0.21, s * 0.21)

    # ---- shield
    shield_rect = QRectF(s * 0.265, s * 0.20, s * 0.47, s * 0.60)
    shield = _shield_path(shield_rect)
    shield_pen = max(1.0, s * 0.052)
    painter.setPen(QPen(SHIELD, shield_pen, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(shield)

    # ---- amber scan band across the shield
    band_top = shield_rect.top() + shield_rect.height() * 0.34
    band = QRectF(shield_rect.left() + shield_pen * 0.9, band_top,
                  shield_rect.width() - shield_pen * 1.8, shield_rect.height() * 0.14)
    if size >= 32:
        clip = QPainterPath()
        clip.addPath(shield)
        painter.save()
        painter.setClipPath(clip)
        band_gradient = QLinearGradient(band.left(), 0, band.right(), 0)
        band_gradient.setColorAt(0.0, ACCENT_DEEP)
        band_gradient.setColorAt(0.55, ACCENT)
        band_gradient.setColorAt(1.0, ACCENT_DEEP)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(band_gradient))
        painter.drawRect(band)
        painter.restore()
    else:
        # too small for the band to read - a solid dot instead
        painter.setPen(Qt.NoPen)
        painter.setBrush(ACCENT)
        r = s * 0.10
        painter.drawEllipse(QPointF(s * 0.5, shield_rect.top() + shield_rect.height() * 0.45),
                            r, r)

    # ---- check mark below the band
    if size >= 24:
        pen = QPen(ACCENT, max(1.2, s * 0.058), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        path = QPainterPath()
        cx, cy = shield_rect.center().x(), shield_rect.top() + shield_rect.height() * 0.70
        path.moveTo(cx - s * 0.085, cy)
        path.lineTo(cx - s * 0.018, cy + s * 0.062)
        path.lineTo(cx + s * 0.098, cy - s * 0.058)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    painter.end()
    return image


def write_ico(path: str, images) -> str:
    """Multi-resolution ICO with PNG-compressed entries (Vista and later)."""
    payloads = []
    for size, image in images:
        # Keep the QByteArray alive: QBuffer does not own it, and letting the
        # temporary die here segfaults the interpreter.
        storage = QByteArray()
        buffer = QBuffer(storage)
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        payloads.append((size, bytes(storage)))
        buffer.close()

    count = len(payloads)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries = b""
    for size, data in payloads:
        dimension = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32,
                               len(data), offset)
        offset += len(data)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(header + entries)
        for _, data in payloads:
            fh.write(data)
    return path


def asset_path(name: str) -> str:
    """Resolve assets/ both in the source tree and inside a frozen bundle."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = os.path.join(base, "assets", name)
        if os.path.exists(candidate):
            return candidate
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "assets", name)


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assets = os.path.join(root, "assets")
    images = [(size, render(size)) for size in SIZES]
    write_ico(os.path.join(assets, "icon.ico"), images)
    render(512).save(os.path.join(assets, "icon.png"))
    print("wrote", os.path.join(assets, "icon.ico"))
    print("wrote", os.path.join(assets, "icon.png"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
