"""Custom widgets matching the Stitch High-Performance Telemetry UI:
- ScoreRing: Compact radial gauge (72px) with centered score and '/ 100'
- HeroVerdictCard: Score ring + status badge + defect summary
- HeroMetricCard: Financial KPI cards (SELLER QUOTED, REPAIR EXPOSURE, DEFECT BUFFER, RECOMMENDED OFFER)
- VerificationRibbon: Seller Claims vs Reality persistent verification strip
- RailCardHeader: Top machine status card in the left rail
- RailItemWidget: Interactive rail row with icons and right-aligned badges
- DefectAuditCard: Exact defect cards with score deductions and repair cost badges
- SensorWaterfallWidget: Real-time dual CPU & GPU waveform sparklines
- SmartRegistersWidget: Decoded S.M.A.R.T. register table
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ..engine import result as R
from . import theme


def _q(colour: str) -> QColor:
    return QColor(colour)


class ScoreRing(QWidget):
    """Compact donut gauge matching Stitch Screen 1 (74px)."""

    def __init__(self, diameter: int = 74, thickness: int = 7,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._score: Optional[float] = None
        self._colour = _q(theme.GREY)
        self._diameter = diameter
        self._thickness = thickness
        self.setFixedSize(diameter, diameter)

    def set_value(self, score: Optional[float], colour: str) -> None:
        self._score = score
        self._colour = _q(colour)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        inset = self._thickness / 2.0 + 2
        rect = QRectF(inset, inset,
                      self._diameter - 2 * inset, self._diameter - 2 * inset)
        start = 225.0
        span = -270.0

        # Background Track
        painter.setPen(QPen(_q("#18202D"), self._thickness, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(rect, int(start * 16), int(span * 16))

        # Filled active arc
        if self._score is not None:
            painter.setPen(QPen(self._colour, self._thickness, Qt.SolidLine, Qt.RoundCap))
            fraction = max(0.0, min(1.0, self._score / 100.0))
            painter.drawArc(rect, int(start * 16), int(span * 16 * fraction))

        # Score Number
        value = "--" if self._score is None else f"{self._score:.0f}"
        font = QFont("Segoe UI Variable Display", 18, QFont.Bold)
        painter.setFont(font)
        painter.setPen(QPen(_q(theme.TEXT)))
        painter.drawText(QRectF(0, self._diameter * 0.22, self._diameter, 24),
                         Qt.AlignCenter, value)

        # / 100 caption
        font = QFont("Cascadia Mono", 8, QFont.Bold)
        painter.setFont(font)
        painter.setPen(QPen(_q(theme.TEXT_FAINT)))
        painter.drawText(QRectF(0, self._diameter * 0.58, self._diameter, 14),
                         Qt.AlignCenter, "/ 100")
        painter.end()


class HeroVerdictCard(QFrame):
    """Card 1 of the 5-card Hero Grid: Score Ring + Verdict Pill + Summary."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("HeroCard")
        self.setFixedHeight(104)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 12, 6)
        row.setSpacing(12)

        self.ring = ScoreRing(68, 6)
        row.addWidget(self.ring)

        mid = QVBoxLayout()
        mid.setSpacing(4)
        mid.addStretch(1)

        self.verdict_pill = QLabel("no scan yet")
        self.verdict_pill.setObjectName("BadgeRed")
        self.verdict_pill.setStyleSheet(
            "font-size: 13px; font-weight: 800; padding: 2px 8px; border-radius: 4px;"
        )
        self.verdict_pill.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        mid.addWidget(self.verdict_pill)

        self.summary_label = QLabel("Run a benchmark to inspect this machine.")
        self.summary_label.setStyleSheet("color: #BCC8D6; font-size: 13.5px;")
        self.summary_label.setWordWrap(True)
        mid.addWidget(self.summary_label)
        mid.addStretch(1)

        row.addLayout(mid, 1)

    def update_verdict(self, score: float, verdict: str, summary: str) -> None:
        colour = theme.VERDICT.get(verdict, theme.GREY)
        self.ring.set_value(score, colour)
        self.verdict_pill.setText(f"{verdict} / COUNTER-OFFER" if verdict != "BUY" else "BUY / VERIFIED")
        if verdict == "BUY":
            self.verdict_pill.setObjectName("BadgeGreen")
        elif verdict == "NEGOTIATE":
            self.verdict_pill.setObjectName("BadgeAmber")
        else:
            self.verdict_pill.setObjectName("BadgeRed")
        self.summary_label.setText(summary)


class HeroMetricCard(QFrame):
    """Cards 2-5 of the 5-card Hero Grid in Stitch."""

    whatsapp_clicked = Signal()

    def __init__(self, title: str, value: str, sub: str,
                 val_color: str = theme.TEXT, is_offer: bool = False,
                 has_whatsapp: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("OfferHeroCard" if is_offer else "HeroCard")
        self.setFixedHeight(104)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        # Header with title & optional icon
        top = QHBoxLayout()
        top.setSpacing(4)
        self.title_lbl = QLabel(title.upper())
        self.title_lbl.setObjectName("Kicker")
        top.addWidget(self.title_lbl)
        top.addStretch(1)
        layout.addLayout(top)

        # Value + WhatsApp button row
        val_row = QHBoxLayout()
        val_row.setSpacing(8)
        self.val_lbl = QLabel(value)
        self.val_lbl.setObjectName("MonoVal")
        self.val_lbl.setStyleSheet(f"font-size: 19.5px; font-weight: 800; color: {val_color};")
        val_row.addWidget(self.val_lbl)
        val_row.addStretch(1)

        if has_whatsapp:
            self.wa_btn = QPushButton("WhatsApp")
            self.wa_btn.setObjectName("WhatsAppPill")
            self.wa_btn.setCursor(Qt.PointingHandCursor)
            self.wa_btn.clicked.connect(self.whatsapp_clicked.emit)
            val_row.addWidget(self.wa_btn)

        layout.addLayout(val_row)

        # Subtitle
        self.sub_lbl = QLabel(sub)
        self.sub_lbl.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 13px;")
        layout.addWidget(self.sub_lbl)

    def set_content(self, value: str, sub: str, val_color: str = theme.TEXT) -> None:
        self.val_lbl.setText(value)
        self.val_lbl.setStyleSheet(f"font-size: 19.5px; font-weight: 800; color: {val_color};")
        self.sub_lbl.setText(sub)


class VerificationRibbon(QFrame):
    """Full-width persistent strip: SELLER CLAIMS VS DETECTED HARDWARE VERIFICATION MATRIX."""

    copy_audit_clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("VerificationRibbon")
        self.setFixedHeight(46)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(9)

        # Left Title
        title_box = QHBoxLayout()
        title_box.setSpacing(6)
        icon_lbl = QLabel("🛡️")
        icon_lbl.setStyleSheet("font-size: 14.5px;")
        title_box.addWidget(icon_lbl)
        title = QLabel("CLAIMS VS DETECTED")
        title.setStyleSheet("font-size: 13px; font-weight: 800; letter-spacing: 0.8px; color: #BCC8D6;")
        title_box.addWidget(title)

        copy_link = QPushButton("Copy Audit")
        copy_link.setStyleSheet("background: transparent; border: none; color: #06B6D4; font-size: 13px; text-decoration: underline;")
        copy_link.setCursor(Qt.PointingHandCursor)
        copy_link.clicked.connect(self.copy_audit_clicked.emit)
        title_box.addWidget(copy_link)
        row.addLayout(title_box)

        row.addSpacing(10)

        # Comparison 1: CPU
        self.cpu_box = QHBoxLayout()
        self.cpu_box.setSpacing(4)
        self.cpu_claim = QLabel("CPU: not stated")
        self.cpu_claim.setObjectName("Mono")
        self.cpu_actual = QLabel("--")
        self.cpu_actual.setStyleSheet("font-size: 14.5px; font-weight: 700; color: #F1F5F9;")
        self.cpu_match = QLabel("--")
        self.cpu_match.setObjectName("BadgeDark")
        self.cpu_box.addWidget(self.cpu_claim)
        self.cpu_box.addWidget(self.cpu_actual)
        self.cpu_box.addWidget(self.cpu_match)
        row.addLayout(self.cpu_box)

        # Comparison 2: RAM
        self.ram_box = QHBoxLayout()
        self.ram_box.setSpacing(4)
        self.ram_claim = QLabel("RAM: not stated")
        self.ram_claim.setObjectName("Mono")
        self.ram_actual = QLabel("--")
        self.ram_actual.setStyleSheet("font-size: 14.5px; font-weight: 700; color: #F1F5F9;")
        self.ram_diff = QLabel("--")
        self.ram_diff.setObjectName("BadgeDark")
        self.ram_cost = QLabel("")
        self.ram_cost.setObjectName("BadgeCyan")
        self.ram_cost.setVisible(False)
        self.ram_box.addWidget(self.ram_claim)
        self.ram_box.addWidget(self.ram_actual)
        self.ram_box.addWidget(self.ram_diff)
        self.ram_box.addWidget(self.ram_cost)
        row.addLayout(self.ram_box)

        # Comparison 3: Storage
        self.disk_box = QHBoxLayout()
        self.disk_box.setSpacing(4)
        self.disk_claim = QLabel("STORAGE: not stated")
        self.disk_claim.setObjectName("Mono")
        self.disk_actual = QLabel("--")
        self.disk_actual.setStyleSheet("font-size: 14.5px; font-weight: 700; color: #F1F5F9;")
        self.disk_tag = QLabel("--")
        self.disk_tag.setObjectName("BadgeDark")
        self.disk_box.addWidget(self.disk_claim)
        self.disk_box.addWidget(self.disk_actual)
        self.disk_box.addWidget(self.disk_tag)
        row.addLayout(self.disk_box)

        row.addStretch(1)

        # Asking Price on right
        ask_box = QHBoxLayout()
        ask_box.setSpacing(6)
        ask_kicker = QLabel("ASKING PRICE:")
        ask_kicker.setObjectName("Kicker")
        self.asking_val = QLabel("not set")
        self.asking_val.setObjectName("BadgeCyan")
        self.asking_val.setStyleSheet("font-size: 14.5px; font-weight: 800; padding: 2px 6px;")
        ask_box.addWidget(ask_kicker)
        ask_box.addWidget(self.asking_val)
        row.addLayout(ask_box)

    def _set_badge(self, label: QLabel, text: str, style_name: str) -> None:
        label.setText(text)
        if label.objectName() != style_name:
            label.setObjectName(style_name)
            label.style().unpolish(label)
            label.style().polish(label)

    def update_matrix(self, claims: Dict[str, Any], machine: Dict[str, Any],
                      asking_price: Optional[int]) -> None:
        """Compare what the seller said against what the scan actually found.

        Every branch has to handle 'not stated' - the tool must never invent a
        mismatch the user never claimed.
        """
        self.asking_val.setText(f"{asking_price:,} PKR" if asking_price else "not set")

        # ---- CPU
        claimed_cpu = str(claims.get("cpu") or "").strip()
        actual_cpu = str(machine.get("cpu") or "").strip()
        short_cpu = actual_cpu
        for noise in ("Intel(R) Core(TM) ", "Intel(R) ", " Core(TM)", " CPU"):
            short_cpu = short_cpu.replace(noise, "")
        short_cpu = short_cpu.split("@")[0].strip()
        self.cpu_actual.setText(short_cpu[:14] or "--")
        if claimed_cpu:
            self.cpu_claim.setText(f"CPU: {claimed_cpu[:10]}")
            hit = claimed_cpu.lower() in actual_cpu.lower()
            self._set_badge(self.cpu_match, "MATCH" if hit else "MISMATCH",
                            "BadgeGreen" if hit else "BadgeRed")
        else:
            self.cpu_claim.setText("CPU: --")
            self._set_badge(self.cpu_match, "", "BadgeDark")

        # ---- RAM
        claimed_ram = claims.get("ram_gb")
        actual_ram = machine.get("ram_gb")
        self.ram_actual.setText(f"{actual_ram:g} GB" if actual_ram else "--")
        if claimed_ram and actual_ram:
            diff = actual_ram - float(claimed_ram)
            self.ram_claim.setText(f"RAM: {float(claimed_ram):g}G")
            if diff < -0.4:
                self._set_badge(self.ram_diff, f"{diff:g} GB", "BadgeRed")
                self.ram_cost.setText("short")
                self.ram_cost.setVisible(True)
            elif diff > 0.4:
                self._set_badge(self.ram_diff, f"+{diff:g} GB", "BadgeGreen")
                self.ram_cost.setVisible(False)
            else:
                self._set_badge(self.ram_diff, "MATCH", "BadgeGreen")
                self.ram_cost.setVisible(False)
        else:
            self.ram_claim.setText("RAM: not stated")
            self._set_badge(self.ram_diff, "unverified", "BadgeDark")
            self.ram_cost.setVisible(False)

        # ---- Storage
        drives = machine.get("storage") or []
        biggest = max(drives, key=lambda d: d.get("size_gb") or 0) if drives else None
        if biggest:
            self.disk_actual.setText(
                f"{biggest.get('size_gb')}GB {biggest.get('media') or ''}".strip()[:16])
        else:
            self.disk_actual.setText("--")

        claimed_gb = claims.get("storage_gb")
        claimed_type = str(claims.get("storage_type") or "").strip().lower()
        if claimed_gb or claimed_type:
            bits = []
            if claimed_gb:
                bits.append(f"{float(claimed_gb):g}GB")
            if claimed_type:
                bits.append(claimed_type.upper())
            self.disk_claim.setText("STORAGE: " + " ".join(bits))
            problems = []
            if claimed_gb and biggest:
                actual_gb = biggest.get("size_gb") or 0
                if actual_gb and actual_gb < float(claimed_gb) * 0.9:
                    problems.append(f"{-int(float(claimed_gb) - actual_gb)}GB short")
            if claimed_type and drives:
                buses = {(d.get("bus") or "").lower() for d in drives}
                medias = {(d.get("media") or "").lower() for d in drives}
                if claimed_type == "nvme" and "nvme" not in buses:
                    problems.append("no NVMe")
                elif claimed_type == "ssd" and "hdd" in medias and "ssd" not in medias:
                    problems.append("HDD fitted")
                elif claimed_type == "hdd" and "ssd" in medias and "hdd" not in medias:
                    problems.append("SSD fitted")
            if problems:
                self._set_badge(self.disk_tag, " · ".join(problems), "BadgeRed")
            else:
                self._set_badge(self.disk_tag, "MATCH", "BadgeGreen")
        else:
            self.disk_claim.setText("STORAGE: not stated")
            self._set_badge(self.disk_tag, "unverified", "BadgeDark")


class RailCardHeader(QFrame):
    """Top mini card inside the left navigation rail."""

    start_stress_clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("HeroCard")
        # Without a minimum the rail squeezes this card and clips the text.
        self.setMinimumHeight(112)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        self.name_lbl = QLabel("No machine scanned")
        self.name_lbl.setStyleSheet("font-size: 15.5px; font-weight: 700; color: #FFFFFF;")
        layout.addWidget(self.name_lbl)

        self.health_lbl = QLabel("Health Index: --")
        self.health_lbl.setStyleSheet("font-size: 13.5px; color: #8FA0B4; font-weight: 600;")
        layout.addWidget(self.health_lbl)

        self.stress_btn = QPushButton("▶ Start Stress Matrix")
        self.stress_btn.setObjectName("Ghost")
        self.stress_btn.setFixedHeight(32)
        self.stress_btn.setStyleSheet(
            "font-size: 13.5px; font-weight: 700; color: #06B6D4; border-color: #1E3A4B;"
        )
        self.stress_btn.clicked.connect(self.start_stress_clicked.emit)
        layout.addWidget(self.stress_btn)


class RailItemWidget(QFrame):
    """Left navigation rail check row with icon and right-aligned badge."""

    clicked = Signal(str)

    def __init__(self, key: str, label: str, icon: str, badge_text: str = "--",
                 badge_style: str = "BadgeDark", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.key = key
        self.label = label
        self._selected = False
        self.setFixedHeight(44)
        self.setCursor(Qt.PointingHandCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(8)

        self.icon_lbl = QLabel(icon)
        self.icon_lbl.setStyleSheet("font-size: 17px;")
        row.addWidget(self.icon_lbl)

        self.text_lbl = QLabel(label)
        self.text_lbl.setStyleSheet("font-size: 15px; font-weight: 600; color: #CBD5E1;")
        row.addWidget(self.text_lbl, 1)

        self.badge = QLabel(badge_text)
        self.badge.setObjectName(badge_style)
        self.badge.setAlignment(Qt.AlignCenter)
        row.addWidget(self.badge)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        if selected:
            self.setStyleSheet(
                "QFrame { background-color: #17202E; border: 1px solid #23334A;"
                " border-left: 3px solid #3B82F6; border-radius: 4px; }"
            )
            self.text_lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #FFFFFF;")
        else:
            self.setStyleSheet("QFrame { background: transparent; border: none; }")
            self.text_lbl.setStyleSheet("font-size: 15px; font-weight: 600; color: #BCC8D6;")

    def set_badge(self, text: str, style_name: str) -> None:
        self.badge.setText(text)
        self.badge.setObjectName(style_name)
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.key)
        super().mousePressEvent(event)


class WrapLabel(QLabel):
    """A label that reports the height its wrapped text actually needs.

    A plain word-wrapped QLabel reports a minimum height as if the text never
    wrapped, so a tight layout squeezes it and the text clips mid-sentence. That
    is what happened to every finding card once the type got larger.
    """

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)
        policy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def _wrapped_height(self) -> int:
        width = self.width()
        if width <= 0:
            width = self.sizeHint().width()
        return self.heightForWidth(width) if width > 0 else -1

    def sizeHint(self):  # noqa: N802
        hint = super().sizeHint()
        needed = self._wrapped_height()
        if needed > 0:
            hint.setHeight(needed)
        return hint

    def minimumSizeHint(self):  # noqa: N802
        hint = super().minimumSizeHint()
        needed = self._wrapped_height()
        if needed > 0:
            hint.setHeight(needed)
        return hint

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        needed = self._wrapped_height()
        if needed > 0 and self.minimumHeight() != needed:
            self.setMinimumHeight(needed)


class DefectAuditCard(QFrame):
    """Detailed defect audit card matching Stitch Screen 1 (Critical, Major, Thermal)."""

    def __init__(self, cat_badge: str, cat_style: str, title: str,
                 score_pts: str, cost_pkr: str, body_text: str,
                 footer_tags: List[tuple], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 12)
        outer.setSpacing(6)

        # Header Row
        head = QHBoxLayout()
        head.setSpacing(8)

        badge = QLabel(cat_badge)
        badge.setObjectName(cat_style)
        badge.setStyleSheet("font-size: 11.5px; font-weight: 800; padding: 2px 6px;")
        head.addWidget(badge)

        title_lbl = WrapLabel(title)
        title_lbl.setStyleSheet("font-size: 16px; font-weight: 700; color: #FFFFFF;")
        head.addWidget(title_lbl, 1)

        outer.addLayout(head)

        # Score and cost on their own line: with the larger type they were
        # squeezing the title and pushing the severity badge off the card.
        meta = QHBoxLayout()
        meta.setSpacing(10)
        pts_lbl = QLabel(score_pts)
        pts_lbl.setStyleSheet("font-size: 13.5px; font-weight: 700; color: #06B6D4;")
        meta.addWidget(pts_lbl)
        cost_lbl = QLabel(cost_pkr)
        cost_lbl.setStyleSheet("font-size: 13.5px; font-weight: 600; color: #CBD5E1;")
        meta.addWidget(cost_lbl)
        meta.addStretch(1)
        outer.addLayout(meta)

        # Description Body
        body = WrapLabel(body_text)
        body.setStyleSheet("color: #BCC8D6; font-size: 14.5px;")
        outer.addWidget(body)

        # Footer Sub-tags
        if footer_tags:
            foot = QHBoxLayout()
            foot.setSpacing(6)
            for tag_text, tag_style in footer_tags:
                tag = QLabel(tag_text)
                tag.setObjectName(tag_style)
                foot.addWidget(tag)
            foot.addStretch(1)
            outer.addLayout(foot)


class SensorWaveformWidget(QWidget):
    """Sparkline drawn from a real sample series.

    No curve is invented: with fewer than two samples it draws a dashed baseline
    and says so, because a plausible-looking line that was never measured is
    worse than an empty box.
    """

    def __init__(self, colour: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(46)
        self._colour = _q(colour)
        self._points: List[float] = []
        self._empty_text = "no samples"

    def set_series(self, values: List[Any], lo: Optional[float] = None,
                   hi: Optional[float] = None, empty_text: str = "no samples") -> None:
        clean = [float(v) for v in values if v is not None]
        self._empty_text = empty_text
        if len(clean) < 2:
            self._points = []
        else:
            low = min(clean) if lo is None else lo
            high = max(clean) if hi is None else hi
            span = (high - low) or 1.0
            self._points = [max(0.0, min(1.0, (v - low) / span)) for v in clean]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()

        if not self._points:
            painter.setPen(QPen(_q("#334155"), 1.0, Qt.DashLine))
            painter.drawLine(0, int(h * 0.7), w, int(h * 0.7))
            font = QFont("Cascadia Mono", 7)
            painter.setFont(font)
            painter.setPen(QPen(_q("#475569")))
            painter.drawText(QRectF(4, h * 0.35, w - 8, 14),
                             Qt.AlignLeft | Qt.AlignVCenter, self._empty_text)
            painter.end()
            return

        n = len(self._points)
        path = QPainterPath()
        for i, value in enumerate(self._points):
            x = w * i / (n - 1)
            y = h * (1.0 - value) * 0.86 + h * 0.07
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)

        fill_path = QPainterPath(path)
        fill_path.lineTo(w, h)
        fill_path.lineTo(0, h)
        fill_path.closeSubpath()

        grad = QLinearGradient(0, 0, 0, h)
        top = QColor(self._colour)
        top.setAlpha(50)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))

        painter.setPen(Qt.NoPen)
        painter.setBrush(grad)
        painter.drawPath(fill_path)

        painter.setPen(QPen(self._colour, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        painter.end()


class SensorWaterfallWidget(QFrame):
    """CPU clock trace from the thermal load test, plus GPU state if measured."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFixedHeight(252)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(6)

        top = QHBoxLayout()
        lbl = QLabel("📈 CPU CLOCK UNDER LOAD")
        lbl.setStyleSheet("font-size: 13px; font-weight: 800; color: #CBD5E1; letter-spacing: 0.8px;")
        self.rate_lbl = QLabel("--")
        self.rate_lbl.setObjectName("Mono")
        self.rate_lbl.setStyleSheet("font-size: 12.5px; color: #06B6D4;")
        top.addWidget(lbl)
        top.addStretch(1)
        top.addWidget(self.rate_lbl)
        outer.addLayout(top)

        cpu_head = QHBoxLayout()
        self.cpu_title = QLabel("CPU Package")
        self.cpu_title.setStyleSheet("font-size: 13.5px; font-weight: 600; color: #CBD5E1;")
        self.cpu_status = QLabel("not measured")
        self.cpu_status.setStyleSheet("font-size: 13px; font-weight: 700; color: #8FA0B4;")
        cpu_head.addWidget(self.cpu_title)
        cpu_head.addStretch(1)
        cpu_head.addWidget(self.cpu_status)
        outer.addLayout(cpu_head)

        self.cpu_graph = SensorWaveformWidget("#F43F5E")
        outer.addWidget(self.cpu_graph)

        gpu_head = QHBoxLayout()
        self.gpu_title = QLabel("GPU Core")
        self.gpu_title.setStyleSheet("font-size: 13.5px; font-weight: 600; color: #CBD5E1;")
        self.gpu_status = QLabel("no sensor")
        self.gpu_status.setStyleSheet("font-size: 13px; font-weight: 700; color: #8FA0B4;")
        gpu_head.addWidget(self.gpu_title)
        gpu_head.addStretch(1)
        gpu_head.addWidget(self.gpu_status)
        outer.addLayout(gpu_head)

        self.gpu_graph = SensorWaveformWidget("#10B981")
        outer.addWidget(self.gpu_graph)

    def set_data(self, thermal: Dict[str, Any], machine: Dict[str, Any],
                 gpu_data: Dict[str, Any]) -> None:
        thermal = thermal or {}
        series = thermal.get("series") or []
        mhz = [p.get("mhz") for p in series]
        nominal = thermal.get("nominal_mhz")

        cpu_name = (machine.get("cpu") or "CPU").replace("(R)", "").replace("(TM)", "")
        self.cpu_title.setText(cpu_name[:34])

        if len(series) >= 2:
            span = series[-1]["t"] - series[0]["t"]
            rate_ms = int(round(span * 1000 / (len(series) - 1)))
            self.rate_lbl.setText(f"Sampling: {rate_ms} ms · {len(series)} pts")
        else:
            self.rate_lbl.setText("no samples")

        self.cpu_graph.set_series(
            mhz, lo=(nominal * 0.5 if nominal else None),
            hi=(max(mhz) * 1.05 if mhz and any(mhz) else None),
            empty_text="thermal test not run")

        temps = [t for t in (thermal.get("temps_c") or []) if isinstance(t, (int, float))]
        sag = thermal.get("sag_ratio")
        bits = []
        if temps:
            bits.append(f"{max(temps):.0f}°C")
        if sag is not None:
            bits.append(f"{sag * 100:.0f}% of peak")
        if not bits:
            self.cpu_status.setText("clock not measured")
            self.cpu_status.setStyleSheet("font-size: 13px; font-weight: 700; color: #8FA0B4;")
        else:
            throttling = sag is not None and sag < 0.85
            self.cpu_status.setText(" · ".join(bits) + (" [THROTTLING]" if throttling else ""))
            colour = "#F43F5E" if throttling else "#10B981"
            self.cpu_status.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {colour};")

        # GPU: this platform exposes no GPU temperature, so say that rather than
        # drawing a line for a sensor that does not exist.
        adapters = (gpu_data or {}).get("adapters") or []
        discrete = [a for a in adapters if a.get("kind") == "discrete"]
        name = (discrete[0]["name"] if discrete else
                (adapters[0]["name"] if adapters else "GPU"))
        self.gpu_title.setText(name[:34])
        stress = (gpu_data or {}).get("stress") or {}
        if stress.get("device_removed"):
            self.gpu_status.setText("driver reset under load")
            self.gpu_status.setStyleSheet("font-size: 13px; font-weight: 700; color: #F43F5E;")
        elif stress.get("available") and stress.get("frames_per_sec"):
            self.gpu_status.setText(f"{stress['frames_per_sec']:,} frames/s · no temp sensor")
            self.gpu_status.setStyleSheet("font-size: 13px; font-weight: 700; color: #10B981;")
        else:
            self.gpu_status.setText("no temperature sensor")
            self.gpu_status.setStyleSheet("font-size: 13px; font-weight: 700; color: #8FA0B4;")
        self.gpu_graph.set_series([], empty_text="GPU temperature not exposed")


class SmartRegistersWidget(QFrame):
    """Decoded S.M.A.R.T. register table for one drive."""

    HEADERS = ["ID", "ATTRIBUTE", "VALUE", "WORST", "RAW", "STATUS"]
    PRIORITY = {9: 0, 197: 1, 5: 2, 198: 3, 187: 4, 12: 5, 194: 6, 199: 7}

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFixedHeight(252)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.title_lbl = QLabel("Drive")
        self.title_lbl.setStyleSheet("font-size: 15px; font-weight: 800; color: #FFFFFF;")
        self.type_lbl = QLabel("DISK")
        self.type_lbl.setObjectName("BadgeDark")
        self.type_lbl.setAlignment(Qt.AlignCenter)
        self.iface_lbl = QLabel("--")
        self.iface_lbl.setObjectName("Mono")
        self.iface_lbl.setStyleSheet("font-size: 12.5px; color: #BCC8D6;")
        top.addWidget(self.title_lbl)
        top.addWidget(self.type_lbl, 0, Qt.AlignVCenter)
        top.addStretch(1)
        top.addWidget(self.iface_lbl)
        outer.addLayout(top)

        # One line of headline numbers, so the two drives are comparable at a glance
        self.detail_lbl = QLabel("")
        self.detail_lbl.setStyleSheet("font-size: 12.5px; color: #BCC8D6;")
        outer.addWidget(self.detail_lbl)

        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 4, 0, 0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(4)
        for col, head in enumerate(self.HEADERS):
            lbl = QLabel(head)
            lbl.setObjectName("Kicker")
            self.grid.addWidget(lbl, 0, col)
        self.grid.setColumnStretch(1, 1)
        outer.addLayout(self.grid)
        outer.addStretch(1)
        self._rows: List[QWidget] = []

    def _set_type(self, text: str, style: str) -> None:
        self.type_lbl.setText(text)
        if self.type_lbl.objectName() != style:
            self.type_lbl.setObjectName(style)
            self.type_lbl.style().unpolish(self.type_lbl)
            self.type_lbl.style().polish(self.type_lbl)

    def _clear_rows(self) -> None:
        for widget in self._rows:
            widget.setParent(None)
        self._rows = []

    def set_drive(self, drive: Optional[Dict[str, Any]]) -> None:
        self._clear_rows()
        if not drive:
            self.title_lbl.setText("No drive read")
            self.iface_lbl.setText("")
            self.detail_lbl.setText("")
            self._set_type("", "BadgeDark")
            return

        model = drive.get("model") or f"Disk {drive.get('index')}"
        self.title_lbl.setText(model[:34])

        media = str(drive.get("media") or "").upper()
        self._set_type(media if media in ("SSD", "HDD") else "DISK",
                       "BadgeGreen" if media == "SSD"
                       else "BadgeAmber" if media == "HDD" else "BadgeDark")

        iface = drive.get("interface") or "?"
        via = drive.get("transport") or "unreadable"
        self.iface_lbl.setText(f"{iface} · {via}")

        smart = drive.get("smart") or {}
        bits = []
        size = drive.get("size_gb")
        if size:
            bits.append(f"{size:g} GB")
        hours = smart.get("power_on_hours")
        if hours:
            bits.append(f"{hours:,} h")
        temp = smart.get("temperature_c")
        if isinstance(temp, (int, float)):
            bits.append(f"{temp:g} C")
        if smart.get("reallocated"):
            bits.append(f"{smart['reallocated']:,} reallocated")
        if smart.get("pending"):
            bits.append(f"{smart['pending']:,} pending")
        if smart.get("crc_errors"):
            bits.append(f"{smart['crc_errors']:,} CRC")
        if smart.get("wear_pct") is not None:
            bits.append(f"{smart['wear_pct']:g}% worn")
        if not drive.get("smart_ok"):
            bits.append("SMART unreadable")
        self.detail_lbl.setText("   ·   ".join(bits) if bits else "no telemetry")

        attrs = drive.get("attributes") or []
        if not attrs:
            note = QLabel(drive.get("smart_error") or "SMART data unavailable")
            note.setStyleSheet("color: #F59E0B; font-size: 13.5px;")
            self.grid.addWidget(note, 1, 0, 1, len(self.HEADERS))
            self._rows.append(note)
            return

        def rank(attr):
            try:
                ident = int(str(attr["id"]), 16)
            except ValueError:
                return 99
            bad = 0 if (attr.get("critical") and (attr.get("raw") or 0) > 0) else 1
            return (bad, self.PRIORITY.get(ident, 50), ident)

        for row, attr in enumerate(sorted(attrs, key=rank)[:5], start=1):
            raw = attr.get("raw")
            has_raw = bool(raw)
            failing = bool(attr.get("critical") and has_raw)
            warning = bool(attr.get("warn") and has_raw and not failing)

            id_lbl = QLabel(str(attr.get("id")))
            id_lbl.setObjectName("Mono")
            self.grid.addWidget(id_lbl, row, 0)

            name_lbl = QLabel(str(attr.get("name"))[:28])
            name_lbl.setStyleSheet("font-size: 13.5px; font-weight: 600; color: #F1F5F9;")
            self.grid.addWidget(name_lbl, row, 1)

            for col, value in ((2, attr.get("value")), (3, attr.get("worst"))):
                lbl = QLabel("--" if value is None else str(value))
                lbl.setObjectName("Mono")
                self.grid.addWidget(lbl, row, col)

            raw_lbl = QLabel("--" if raw is None else f"{int(raw):,}"
                             if isinstance(raw, int) else str(raw))
            raw_lbl.setObjectName("Mono")
            raw_lbl.setStyleSheet("color: #EF4444;" if failing
                                 else "color: #F59E0B;" if warning else "color: #CBD5E1;")
            self.grid.addWidget(raw_lbl, row, 4)

            status = QLabel("FAIL" if failing else "WARN" if warning else "OK")
            status.setObjectName("BadgeRed" if failing
                                 else "BadgeAmber" if warning else "BadgeGreen")
            status.setAlignment(Qt.AlignCenter)
            self.grid.addWidget(status, row, 5)

            self._rows.extend([id_lbl, name_lbl, raw_lbl, status])
