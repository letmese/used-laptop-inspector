"""A minimal PDF writer - no reportlab, no Qt, no dependencies.

Why hand-roll it: the report has to be generated from WinPE later, on a machine
with no Python packages installed at all. 300 lines of PDF beats a 4 MB
dependency that has to be frozen into the binary and licensed.

Only the built-in Helvetica faces are used, with WinAnsi-safe text. Anything
outside ASCII is transliterated, which keeps the file valid without embedding a
font. Rupee is written "PKR" for the same reason.
"""

from __future__ import annotations

import zlib
from typing import List, Optional, Sequence, Tuple

A4 = (595.28, 841.89)

# Helvetica advance widths for ASCII 32..126, per 1000 units of em.
_W_REGULAR = [
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
]
_W_BOLD = [
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
    975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
    333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
    611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584,
]

_TRANSLITERATE = {
    "\u2014": "-", "\u2013": "-", "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"', "\u2022": "-", "\u2026": "...",
    "\u20b9": "PKR", "\u00b0": " deg", "\u00d7": "x", "\u2265": ">=",
    "\u2264": "<=", "\u2192": "->", "\u00a0": " ", "\u03c2": "",
}


def _ascii(text: str) -> str:
    out = []
    for ch in str(text):
        if ch in _TRANSLITERATE:
            out.append(_TRANSLITERATE[ch])
        elif ord(ch) < 128:
            out.append(ch)
        elif ord(ch) < 256:
            out.append(ch)  # latin-1 is fine in WinAnsi for most of it
        else:
            out.append("?")
    return "".join(out)


def _escape(text: str) -> bytes:
    raw = _ascii(text).encode("cp1252", "replace")
    out = bytearray()
    for byte in raw:
        if byte in (0x28, 0x29, 0x5C):  # ( ) \
            out.append(0x5C)
            out.append(byte)
        elif byte == 0x0A:
            out.extend(b" ")
        elif byte == 0x0D:
            continue
        else:
            out.append(byte)
    return bytes(out)


def text_width(text: str, size: float, bold: bool = False) -> float:
    table = _W_BOLD if bold else _W_REGULAR
    total = 0
    for ch in _ascii(text):
        code = ord(ch)
        if 32 <= code <= 126:
            total += table[code - 32]
        elif code < 32:
            continue
        else:
            total += 556
    return total * size / 1000.0


class PdfCanvas:
    """Top-left origin API. Colours are 0..1 RGB tuples."""

    def __init__(self, path: str, size: Tuple[float, float] = A4) -> None:
        self.path = path
        self.width, self.height = size
        self._pages: List[bytes] = []
        self._buf: List[str] = []
        self.add_page()

    # ---- pages
    def add_page(self) -> None:
        if self._buf:
            self._pages.append("\n".join(self._buf).encode("cp1252", "replace"))
        self._buf = []

    def _y(self, y: float) -> float:
        return self.height - y

    # ---- primitives
    def rect(self, x: float, y: float, w: float, h: float,
             fill: Optional[Sequence[float]] = None,
             stroke: Optional[Sequence[float]] = None,
             lw: float = 0.5) -> None:
        if fill:
            self._buf.append(f"{fill[0]:.3f} {fill[1]:.3f} {fill[2]:.3f} rg")
        if stroke:
            self._buf.append(f"{stroke[0]:.3f} {stroke[1]:.3f} {stroke[2]:.3f} RG")
            self._buf.append(f"{lw:.2f} w")
        op = "B" if (fill and stroke) else "f" if fill else "S"
        self._buf.append(
            f"{x:.2f} {self._y(y + h):.2f} {w:.2f} {h:.2f} re {op}")

    def line(self, x1: float, y1: float, x2: float, y2: float,
             color: Sequence[float] = (0.8, 0.8, 0.8), lw: float = 0.5) -> None:
        self._buf.append(f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} RG")
        self._buf.append(f"{lw:.2f} w")
        self._buf.append(
            f"{x1:.2f} {self._y(y1):.2f} m {x2:.2f} {self._y(y2):.2f} l S")

    def text(self, x: float, y: float, s: str, size: float = 9,
             bold: bool = False, color: Sequence[float] = (0, 0, 0)) -> None:
        if s == "" or s is None:
            return
        font = "F2" if bold else "F1"
        self._buf.append(f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg")
        self._buf.append("BT")
        self._buf.append(f"/{font} {size:.2f} Tf")
        self._buf.append(f"1 0 0 1 {x:.2f} {self._y(y):.2f} Tm")
        # keep the buffer all-str; _escape emits cp1252 bytes, so round-trip it
        self._buf.append("(" + _escape(s).decode("cp1252", "replace") + ") Tj")
        self._buf.append("ET")

    def text_right(self, x_right: float, y: float, s: str, size: float = 9,
                   bold: bool = False, color: Sequence[float] = (0, 0, 0)) -> None:
        self.text(x_right - text_width(s, size, bold), y, s, size, bold, color)

    def text_center(self, x_center: float, y: float, s: str, size: float = 9,
                    bold: bool = False, color: Sequence[float] = (0, 0, 0)) -> None:
        self.text(x_center - text_width(s, size, bold) / 2.0, y, s, size, bold, color)

    # ---- layout helpers
    @staticmethod
    def wrap(s: str, width: float, size: float, bold: bool = False) -> List[str]:
        words = str(s or "").split()
        lines: List[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if text_width(candidate, size, bold) <= width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def paragraph(self, x: float, y: float, s: str, width: float,
                  size: float = 8.5, leading: float = 11,
                  bold: bool = False,
                  color: Sequence[float] = (0, 0, 0),
                  max_lines: int = 99) -> float:
        """Returns the y after the last line."""
        for line in self.wrap(s, width, size, bold)[:max_lines]:
            self.text(x, y, line, size, bold, color)
            y += leading
        return y

    def truncate(self, s: str, width: float, size: float,
                 bold: bool = False) -> str:
        s = str(s or "")
        if text_width(s, size, bold) <= width:
            return s
        while s and text_width(s + "...", size, bold) > width:
            s = s[:-1]
        return s + "..."

    # ---- output
    def save(self) -> str:
        if self._buf:
            self._pages.append("\n".join(self._buf).encode("cp1252", "replace"))
            self._buf = []

        objects: List[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        font_regular = add(b"<< /Type /Font /Subtype /Type1 "
                           b"/BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        font_bold = add(b"<< /Type /Font /Subtype /Type1 "
                        b"/BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

        # page objects are reserved first so Kids can reference them
        page_ids = [add(b"") for _ in self._pages]
        content_ids = [add(b"") for _ in self._pages]
        pages_id = add(b"")

        for i, (page_id, content_id, stream) in enumerate(
                zip(page_ids, content_ids, self._pages)):
            compressed = zlib.compress(stream, 9)
            objects[content_id - 1] = (
                b"<< /Length " + str(len(compressed)).encode() +
                b" /Filter /FlateDecode >>\nstream\n" + compressed +
                b"\nendstream")
            objects[page_id - 1] = (
                b"<< /Type /Page /Parent " + str(pages_id).encode() +
                b" 0 R /MediaBox [0 0 " +
                f"{self.width:.2f} {self.height:.2f}".encode() +
                b"] /Resources << /Font << /F1 " + str(font_regular).encode() +
                b" 0 R /F2 " + str(font_bold).encode() +
                b" 0 R >> >> /Contents " + str(content_id).encode() + b" 0 R >>")

        kids = " ".join(f"{pid} 0 R" for pid in page_ids)
        objects[pages_id - 1] = (
            b"<< /Type /Pages /Kids [" + kids.encode() +
            b"] /Count " + str(len(page_ids)).encode() + b" >>")
        catalog_id = add(
            b"<< /Type /Catalog /Pages " + str(pages_id).encode() + b" 0 R >>")

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for idx, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{idx} 0 obj\n".encode() + body + b"\nendobj\n"

        xref_pos = len(out)
        out += f"xref\n0 {len(objects) + 1}\n".encode()
        out += b"0000000000 65535 f \n"
        for offset in offsets[1:]:
            out += f"{offset:010d} 00000 n \n".encode()
        out += (f"trailer\n<< /Size {len(objects) + 1} /Root "
                f"{catalog_id} 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n").encode()

        with open(self.path, "wb") as fh:
            fh.write(bytes(out))
        return self.path
