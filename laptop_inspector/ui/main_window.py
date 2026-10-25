"""Main window for Used Laptop Inspector PRO.

Implements the exact Windows 11 Fluent Telemetry UI from Stitch:
- Top bar with diagnostic tabs, machine chip, Admin Direct SMART pill, and Full Benchmark CTA
- Full-width persistent SELLER CLAIMS VS DETECTED HARDWARE VERIFICATION MATRIX
- 5 side-by-side Hero Metric Cards (Verdict, Seller Quoted, Repair Exposure, Defect Buffer, Recommended Offer with WhatsApp CTA)
- Left rail with top machine card, check items with status badges, and bottom calibration items
- Right evidence deck with Critical/Major/Thermal defect cards
- Dual bottom split: Real-Time Sensor Waterfall + S.M.A.R.T. Raw Telemetry Registers
- Bottom footer with benchmark telemetry hash and export action buttons
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QSizePolicy, QSpinBox,
                               QSplitter, QTextEdit, QToolButton, QVBoxLayout,
                               QWidget)

from .. import TOOL_NAME, __version__
from ..engine import result as R
from ..engine import winapi
from ..engine.context import Options
from ..report import html_report, json_report, pdf_report
from . import theme
from .icon import asset_path
from .tests.panel import InteractivePanel
from .widgets import (DefectAuditCard, HeroMetricCard, HeroVerdictCard,
                      RailCardHeader, RailItemWidget, ScoreRing,
                      SensorWaterfallWidget, SmartRegistersWidget,
                      VerificationRibbon)

VERDICT_ROW = "__verdict__"

RAIL_SPECS = [
    (VERDICT_ROW, "Verdict & Offer", "✓"),
    ("thermal", "CPU & Thermals", "⚙"),
    ("battery", "Battery", "🔋"),
    ("storage", "Storage & SMART", "💾"),
    ("dgpu", "Discrete GPU", "🎮"),
    ("specs", "Memory", "⚡"),
    ("gpu", "Display & Chassis", "🖥️"),
    ("peripherals", "Radios & Ports", "📶"),
    ("interactive", "Interactive Tests", "🧪"),
]


PERIPHERAL_LABELS = [
    ("wifi", "WiFi"), ("bluetooth", "Bluetooth"), ("camera", "Camera"),
    ("ethernet", "Ethernet"), ("modem", "Modem"),
    ("card_reader", "Card reader"), ("fingerprint", "Fingerprint"),
    ("audio", "Audio"),
]


def _drive_badness(drive: dict) -> int:
    """How much trouble a drive is in. Unreadable beats any attribute count."""
    smart = drive.get("smart") or {}
    if not drive.get("smart_ok"):
        return 10 ** 9
    return ((smart.get("pending") or 0) * 1000
            + (smart.get("uncorrectable") or 0) * 500
            + (smart.get("reallocated") or 0) * 100
            + (smart.get("crc_errors") or 0))


def _worst_drive(check) -> Optional[dict]:
    """The drive most worth showing: unreadable beats failing beats healthy."""
    drives = ((check.data or {}).get("drives") if check else None) or []
    if not drives:
        return None

    return max(drives, key=_drive_badness)


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
        elif item.layout() is not None:
            _clear(item.layout())


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Used Laptop Inspector PRO  v2.0.4  [Enterprise Diagnostic Engine]")
        self.setWindowIcon(QIcon(asset_path("icon.ico")))
        self.resize(1560, 1000)
        self.setMinimumSize(1160, 720)

        self.report: Optional[R.Report] = None
        self.worker = None
        self.rail_items: Dict[str, RailItemWidget] = {}
        self.selected = VERDICT_ROW
        self._scanning = False
        self.interactive_results: Dict[str, Dict[str, object]] = {}

        self._build()
        self.setStyleSheet(theme.STYLESHEET)

        # Reprice as soon as the asking price or a claim changes, debounced so a
        # typed number does not rebuild the report on every keystroke.
        self._claims_auto_shown = False
        self._reprice_timer = QTimer(self)
        self._reprice_timer.setSingleShot(True)
        self._reprice_timer.setInterval(400)
        self._reprice_timer.timeout.connect(self._reprice)
        self.asking.valueChanged.connect(lambda *_: self._reprice_timer.start())
        for widget in (self.claim_cpu, self.claim_ram, self.claim_disk,
                       self.claim_gpu):
            widget.editingFinished.connect(lambda *_: self._reprice_timer.start())
        self.claim_type.currentIndexChanged.connect(
            lambda *_: self._reprice_timer.start())

        # Trigger initial scan or load live/mock telemetry for instant presentation
        QTimer.singleShot(100, self.start_scan)

    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 1. Top Bar / App Navigation Header
        outer.addWidget(self._build_topbar())

        # 2. Claims Configuration Panel (Collapsible)
        self.claims_panel = self._build_claims_config()
        outer.addWidget(self.claims_panel)

        # 3. Persistent Verification Ribbon (Seller Claims vs Reality)
        self.ribbon = VerificationRibbon()
        self.ribbon.copy_audit_clicked.connect(self.copy_whatsapp_pitch)
        outer.addWidget(self.ribbon)

        # 4. 5 Side-by-Side Hero Cards (Hero Grid)
        outer.addWidget(self._build_hero_grid())

        # 5. Splitter: Left Rail + Right Detail Stage
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.addWidget(self._build_rail())
        splitter.addWidget(self._build_detail_stage())
        splitter.setSizes([310, 1250])
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter, 1)

        # 6. Bottom Status & Export Bar
        outer.addWidget(self._build_footer())

    # ---------------------------------------------------------------- Top Bar
    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Topbar")
        bar.setFixedHeight(66)
        bar.setStyleSheet(f"QFrame#Topbar {{ background-color: {theme.SURFACE}; border-bottom: 1px solid {theme.BORDER_SOFT}; }}")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(10)

        # Brand icon & title
        mark = QLabel()
        mark.setPixmap(QIcon(asset_path("icon.ico")).pixmap(24, 24))
        mark.setFixedSize(24, 24)
        row.addWidget(mark)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title_top = QHBoxLayout()
        title_top.setSpacing(6)
        name = QLabel("Used Laptop Inspector PRO")
        name.setStyleSheet("font-size: 16px; font-weight: 800; color: #FFFFFF;")
        title_top.addWidget(name)

        title_box.addLayout(title_top)
        row.addLayout(title_box)

        row.addSpacing(10)

        row.addStretch(1)

        # Target Hardware Chip
        self.chip_box = QFrame()
        self.chip_box.setObjectName("Card")
        chip_layout = QHBoxLayout(self.chip_box)
        chip_layout.setContentsMargins(8, 4, 8, 4)
        chip_layout.setSpacing(6)
        dot = QLabel("●")
        dot.setStyleSheet("color: #10B981; font-size: 10.5px;")
        chip_layout.addWidget(dot)

        self.chip_label = QLabel("No machine scanned")
        self.chip_label.setStyleSheet("font-size: 14.5px; font-weight: 700; color: #E2E8F0;")
        chip_layout.addWidget(self.chip_label)
        row.addWidget(self.chip_box)

        # Admin Badge - reflects the real token, not a claim
        self.admin_pill = QLabel("elevation unknown")
        self.admin_pill.setObjectName("BadgeDark")
        self.admin_pill.setStyleSheet("font-size: 13px; font-weight: 800; padding: 4px 8px;")
        row.addWidget(self.admin_pill)

        # Fast Test Pill
        self.fast_mode = QCheckBox("FAST TEST (15s)")
        self.fast_mode.setStyleSheet("font-size: 13px; font-weight: 700; color: #BCC8D6;")
        self.fast_mode.setChecked(True)
        row.addWidget(self.fast_mode)

        # Quick Export dropdown
        self.export_btn = QPushButton("Quick Export")
        self.export_btn.setObjectName("Ghost")
        self.export_btn.setFixedHeight(34)
        menu = QMenu(self)
        menu.addAction("Export PDF Certificate", lambda: self.export("pdf"))
        menu.addAction("Portable HTML Evidence", lambda: self.export("html"))
        menu.addAction("Raw JSON Telemetry", lambda: self.export("json"))
        self.export_btn.setMenu(menu)
        row.addWidget(self.export_btn)

        # Claims Toggle
        self.claims_toggle = QPushButton("Claims")
        self.claims_toggle.setObjectName("Ghost")
        self.claims_toggle.setFixedHeight(34)
        self.claims_toggle.setCheckable(True)
        self.claims_toggle.toggled.connect(self._toggle_claims)
        row.addWidget(self.claims_toggle)

        # Primary Full Benchmark CTA Button
        self.scan_btn = QPushButton("⚡ Run Full Benchmark")
        self.scan_btn.setObjectName("Primary")
        self.scan_btn.setFixedHeight(34)
        self.scan_btn.setStyleSheet("background-color: #2563EB; font-weight: 800; font-size: 15px; border-radius: 4px;")
        self.scan_btn.clicked.connect(self.start_scan)
        row.addWidget(self.scan_btn)

        return bar

    def _build_claims_config(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("ClaimsPanel")
        panel.setVisible(False)
        panel.setStyleSheet(f"QFrame#ClaimsPanel {{ background-color: {theme.SURFACE_2}; border-bottom: 1px solid {theme.BORDER}; }}")
        outer = QHBoxLayout(panel)
        outer.setContentsMargins(14, 8, 14, 8)
        outer.setSpacing(10)

        def field(caption: str, widget: QWidget, width: int) -> QWidget:
            holder = QWidget()
            col = QVBoxLayout(holder)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(2)
            cap = QLabel(caption.upper())
            cap.setObjectName("Kicker")
            widget.setFixedWidth(width)
            widget.setFixedHeight(30)
            col.addWidget(cap)
            col.addWidget(widget)
            return holder

        self.claim_cpu = QLineEdit()
        self.claim_cpu.setPlaceholderText("as advertised, e.g. i7-2820QM")
        self.claim_ram = QLineEdit()
        self.claim_ram.setPlaceholderText("GB")
        self.claim_disk = QLineEdit()
        self.claim_disk.setPlaceholderText("GB")
        self.claim_type = QComboBox()
        self.claim_type.addItems(["any", "nvme", "ssd", "hdd"])
        self.claim_gpu = QLineEdit()
        self.claim_gpu.setPlaceholderText("as advertised")
        self.asking = QSpinBox()
        self.asking.setRange(0, 2_000_000)
        self.asking.setValue(0)
        self.asking.setGroupSeparatorShown(True)
        self.asking.setSpecialValueText("not given")
        self.asking.setSuffix(" PKR")
        # What the model sells for used. This is what the offer is built from -
        # the asking price only decides whether the deal is good or bad.
        self.market = QSpinBox()
        self.market.setRange(0, 2_000_000)
        self.market.setValue(0)
        self.market.setGroupSeparatorShown(True)
        self.market.setSpecialValueText("auto / not set")
        self.market.setSuffix(" PKR")
        self.market.setToolTip("Used-market price for this model. Leave at "
                               "\"auto\" to search for it, or type what you know "
                               "it sells for locally.")
        self.thermal_seconds = QSpinBox()
        self.thermal_seconds.setRange(5, 300)
        self.thermal_seconds.setValue(15)
        self.thermal_seconds.setSuffix(" s")

        for widget, caption, width in (
                (self.claim_cpu, "cpu claim", 100),
                (self.claim_ram, "ram claim", 65),
                (self.claim_disk, "disk claim", 70),
                (self.claim_type, "disk type", 85),
                (self.claim_gpu, "gpu claim", 100),
                (self.asking, "asking price", 115),
                (self.market, "market price", 130),
                (self.thermal_seconds, "load test", 70)):
            outer.addWidget(field(caption, widget, width))

        outer.addStretch(1)
        return panel

    def _toggle_claims(self, shown: bool) -> None:
        self.claims_panel.setVisible(shown)

    def _reprice(self) -> None:
        """Recompute the counter-offer from the report already on screen.

        Changing the asking price used to do nothing until the machine was
        rescanned, which is a 30 second wait to answer a one-number question.
        The scan results are unchanged, so only the negotiation needs rebuilding.
        """
        if not self.report:
            return
        from ..engine.inspector import Inspector
        options = Options(asking_price_pkr=self.asking.value() or None,
                          market_price_pkr=self.market.value() or None,
                          claims=self._claims())
        Inspector(options).finalise(self.report)
        self.on_report(self.report)

    def _toggle_claims_from_rail(self, *_) -> None:
        self.claims_toggle.setChecked(not self.claims_toggle.isChecked())

    # ---------------------------------------------------------------- Hero Grid (5 Cards)
    def _build_hero_grid(self) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)

        # Card 1: Score & Verdict Card
        self.card_verdict = HeroVerdictCard()
        row.addWidget(self.card_verdict, 2)

        # Card 2: SELLER QUOTED
        self.card_quoted = HeroMetricCard("SELLER QUOTED", "not given", "enter it under Claims", theme.TEXT_DIM)
        row.addWidget(self.card_quoted, 1)

        # Card 3: REPAIR EXPOSURE
        self.card_repair = HeroMetricCard("REPAIR EXPOSURE", "0 PKR", "no repairable defects", theme.TEXT_DIM)
        row.addWidget(self.card_repair, 1)

        # Card 4: DEFECT BUFFER (10%)
        self.card_buffer = HeroMetricCard("DEFECT BUFFER (10%)", "0 PKR", "10% risk allowance", theme.TEXT_DIM)
        row.addWidget(self.card_buffer, 1)

        # Card 5: RECOMMENDED MAX OFFER (Highlighted)
        self.card_offer = HeroMetricCard(
            "RECOMMENDED MAX OFFER", "--", "set an asking price",
            theme.TEXT_DIM, is_offer=True, has_whatsapp=True
        )
        self.card_offer.whatsapp_clicked.connect(self.copy_whatsapp_pitch)
        row.addWidget(self.card_offer, 1)

        return container

    # ---------------------------------------------------------------- Left Rail
    def _build_rail(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(240)
        panel.setMaximumWidth(320)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(14, 0, 6, 8)
        outer.setSpacing(6)

        # Top machine / stress card
        self.rail_header = RailCardHeader()
        self.rail_header.start_stress_clicked.connect(self.start_scan)
        outer.addWidget(self.rail_header)

        # Items
        for key, label, icon in RAIL_SPECS:
            item = RailItemWidget(key, label, icon, "--", "BadgeDark")
            item.clicked.connect(self.select_rail_item)
            self.rail_items[key] = item
            outer.addWidget(item)

        outer.addStretch(1)

        # Bottom pinned items
        settings_item = RailItemWidget("__settings__", "Claims", "⚙", "", "BadgeDark")
        settings_item.clicked.connect(self._toggle_claims_from_rail)
        script_item = RailItemWidget("__script__", "Export Script", "📋", "", "BadgeDark")
        script_item.clicked.connect(self.copy_whatsapp_pitch)
        outer.addWidget(settings_item)
        outer.addWidget(script_item)

        # Set first item selected
        if VERDICT_ROW in self.rail_items:
            self.rail_items[VERDICT_ROW].set_selected(True)

        # Scroll rather than squeeze: with the larger type the rail is taller
        # than a 1000px window, and a compressed rail clips its own labels.
        scroll = QScrollArea()
        scroll.setObjectName("RailScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(250)
        scroll.setMaximumWidth(320)
        return scroll

    # ---------------------------------------------------------------- Detail Stage
    def _build_detail_stage(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        self.detail_layout = QVBoxLayout(holder)
        self.detail_layout.setContentsMargins(8, 0, 14, 12)
        self.detail_layout.setSpacing(10)
        scroll.setWidget(holder)

        self._render_default_evidence_deck()
        return scroll

    # ------------------------------------------------------- evidence helpers
    def _all_findings(self) -> List[tuple]:
        """Every finding in the report, worst first. Blocking outranks severity."""
        if not self.report:
            return []
        order = {"critical": 0, "major": 1, "warn": 2, "info": 3}
        pairs = [(c, f) for c in self.report.checks for f in c.findings]
        pairs.sort(key=lambda p: (-int(p[1].blocking), order.get(p[1].severity, 9)))
        return pairs

    def _device_list(self, check: R.CheckResult) -> QFrame:
        """What is actually fitted, and which generation of radio it is."""
        frame = QFrame()
        frame.setObjectName("Card")
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(16, 12, 16, 14)
        outer.setSpacing(8)

        title = QLabel("DEVICES FITTED")
        title.setStyleSheet("font-size: 12.5px; font-weight: 800;"
                            " color: #8593A6; letter-spacing: 1px;")
        outer.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        for col, head in enumerate(("HARDWARE", "DEVICE", "TYPE", "STATE")):
            lbl = QLabel(head)
            lbl.setObjectName("Kicker")
            grid.addWidget(lbl, 0, col)
        grid.setColumnStretch(1, 1)

        devices_by_key = (check.data or {}).get("devices") or {}
        model_derived = False
        row = 1
        for key, label in PERIPHERAL_LABELS:
            devices = devices_by_key.get(key) or []
            if not devices:
                name = QLabel(f"{label}")
                name.setStyleSheet("font-size: 13.5px; font-weight: 600;"
                                   " color: #BCC8D6;")
                grid.addWidget(name, row, 0)
                missing = QLabel("not fitted")
                missing.setStyleSheet("font-size: 13.5px; color: #8593A6;")
                grid.addWidget(missing, row, 1, 1, 2)
                badge = QLabel("—")
                badge.setObjectName("BadgeDark")
                badge.setAlignment(Qt.AlignCenter)
                grid.addWidget(badge, row, 3)
                row += 1
                continue

            for index, device in enumerate(devices[:2]):
                if index == 0:
                    name = QLabel(label)
                    name.setStyleSheet("font-size: 13.5px; font-weight: 600;"
                                       " color: #BCC8D6;")
                    grid.addWidget(name, row, 0)

                dev_lbl = QLabel(str(device.get("name") or "?")[:40])
                dev_lbl.setStyleSheet("font-size: 13.5px; color: #F1F5F9;")
                grid.addWidget(dev_lbl, row, 1)

                radio = ""
                if key == "wifi":
                    generation = device.get("generation") or ""
                    standard = device.get("standard") or ""
                    radio = (f"{generation} ({standard})" if generation
                             else standard)
                elif key == "ethernet":
                    radio = device.get("speed") or ""
                elif key == "bluetooth":
                    version = device.get("version") or ""
                    if version:
                        radio = f"BT {version}"
                        if device.get("version_source") == "model":
                            radio += " *"
                            model_derived = True
                radio_lbl = QLabel(radio or "—")
                radio_lbl.setStyleSheet("font-size: 13px; font-weight: 700;"
                                        " color: #06B6D4;" if radio
                                        else "font-size: 13px; color: #5A6779;")
                grid.addWidget(radio_lbl, row, 2)

                state = str(device.get("status") or "ok")
                link = str(device.get("link") or "")
                if state.lower() == "up" and link:
                    state = f"up {link}"
                badge = QLabel(state.upper())
                badge.setObjectName("BadgeGreen" if device.get("ok") else "BadgeRed")
                badge.setAlignment(Qt.AlignCenter)
                grid.addWidget(badge, row, 3)
                row += 1

        outer.addLayout(grid)

        if model_derived:
            note = QLabel("* Windows did not report the Bluetooth version; this "
                          "is the spec of that controller model.")
            note.setStyleSheet("font-size: 11.5px; color: #8593A6;")
            note.setWordWrap(True)
            outer.addWidget(note)
        return frame

    def _finding_card(self, check: R.CheckResult, finding: R.Finding) -> DefectAuditCard:
        style = {"critical": "BadgeRed", "major": "BadgeAmber",
                 "warn": "BadgeCyan", "info": "BadgeDark"}.get(finding.severity, "BadgeDark")
        cat = finding.severity.upper() + (" · BLOCKING" if finding.blocking else "")
        pts = f"{check.score:.0f}/100" if check.scored else "unscored"
        if getattr(finding, "upgrade", False) and finding.cost_pkr:
            # Not a repair, so it must not read like one - it is not deducted
            # from the offer.
            cost = f"Upgrade: {finding.cost_pkr:,} PKR"
        else:
            cost = (f"Cost: {finding.cost_pkr:,} PKR" if finding.cost_pkr
                    else "Non-monetary")
        tags = [(f"{k}: {v}", "BadgeDark")
                for k, v in list(finding.evidence.items())[:3]
                if not isinstance(v, (dict, list)) and v not in (None, "")]
        return DefectAuditCard(cat, style, finding.title, pts, cost,
                               finding.detail or "No further detail recorded.", tags)

    def _engine_note(self) -> str:
        """Say how the data was actually obtained, not a driver name we invented."""
        if not self.report:
            return "no scan yet"
        storage = self.report.check("storage")
        transports = {
            (d.get("transport") or "none")
            for d in ((storage.data or {}).get("drives") or [])
        } if storage else set()
        if "predict_failure" in transports:
            return "SMART via IOCTL_STORAGE_PREDICT_FAILURE"
        if "nvme_ioctl" in transports:
            return "SMART via NVMe health log"
        if "smart_ioctl" in transports:
            return "SMART via ATA pass-through"
        if transports:
            return "SMART unavailable"
        return "offline · native Windows APIs"

    def _render_default_evidence_deck(self) -> None:
        _clear(self.detail_layout)

        head = QHBoxLayout()
        icon = QLabel("📝")
        icon.setStyleSheet("font-size: 15.5px;")
        head.addWidget(icon)
        title = QLabel("HARDWARE EVIDENCE & DEFECT AUDIT LOG")
        title.setStyleSheet("font-size: 14.5px; font-weight: 800; color: #FFFFFF; letter-spacing: 0.8px;")
        head.addWidget(title)
        head.addStretch(1)
        engine = QLabel(self._engine_note() + " ●")
        engine.setObjectName("Mono")
        engine.setStyleSheet("font-size: 13px; color: #10B981; font-weight: 600;")
        head.addWidget(engine)
        self.detail_layout.addLayout(head)

        if not self.report:
            empty = QFrame()
            empty.setObjectName("Card")
            box = QVBoxLayout(empty)
            box.setContentsMargins(16, 16, 16, 16)
            note = QLabel("No scan yet. Run a benchmark to populate the audit log.")
            note.setStyleSheet("color: #BCC8D6; font-size: 15.5px;")
            box.addWidget(note)
            self.detail_layout.addWidget(empty)
            self.detail_layout.addStretch(1)
            return

        pairs = self._all_findings()
        if not pairs:
            clean = QFrame()
            clean.setObjectName("Card")
            box = QVBoxLayout(clean)
            box.setContentsMargins(16, 16, 16, 16)
            note = QLabel("✓ No defects found. Every check passed.")
            note.setStyleSheet("color: #10B981; font-weight: 700; font-size: 15.5px;")
            box.addWidget(note)
            self.detail_layout.addWidget(clean)
        else:
            for check, finding in pairs[:6]:
                self.detail_layout.addWidget(self._finding_card(check, finding))
            if len(pairs) > 6:
                more = QLabel(f"+ {len(pairs) - 6} more finding(s) across the checks")
                more.setStyleSheet("color: #8FA0B4; font-size: 13.5px;")
                self.detail_layout.addWidget(more)

        # Bottom split: real CPU trace and real SMART registers
        split_row = QHBoxLayout()
        split_row.setSpacing(10)

        thermal = self.report.check("thermal")
        gpu = self.report.check("gpu")
        waterfall = SensorWaterfallWidget()
        waterfall.set_data((thermal.data if thermal else {}) or {},
                           self.report.machine, (gpu.data if gpu else {}) or {})
        split_row.addWidget(waterfall, 1)

        storage = self.report.check("storage")
        smart = SmartRegistersWidget()
        smart.set_drive(_worst_drive(storage))
        split_row.addWidget(smart, 1)

        self.detail_layout.addLayout(split_row)
        self.detail_layout.addStretch(1)

    # ---------------------------------------------------------------- Footer
    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("Footer")
        footer.setFixedHeight(46)
        footer.setStyleSheet(f"QFrame#Footer {{ background-color: {theme.SURFACE}; border-top: 1px solid {theme.BORDER_SOFT}; }}")
        row = QHBoxLayout(footer)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(12)

        dot = QLabel("●")
        dot.setStyleSheet("color: #10B981; font-size: 10.5px;")
        row.addWidget(dot)

        self.status_lbl = QLabel("No scan yet · nothing measured")
        self.status_lbl.setObjectName("Mono")
        self.status_lbl.setStyleSheet("font-size: 13.5px; color: #BCC8D6;")
        row.addWidget(self.status_lbl, 1)

        # Export buttons
        pdf_btn = QPushButton("Export PDF Certificate")
        pdf_btn.setObjectName("Ghost")
        pdf_btn.setFixedHeight(32)
        pdf_btn.clicked.connect(lambda: self.export("pdf"))
        row.addWidget(pdf_btn)

        html_btn = QPushButton("Portable HTML Evidence")
        html_btn.setObjectName("Ghost")
        html_btn.setFixedHeight(32)
        html_btn.clicked.connect(lambda: self.export("html"))
        row.addWidget(html_btn)

        wa_btn = QPushButton("Copy Counter-Offer Script (Urdu/Eng)")
        wa_btn.setObjectName("GreenCTA")
        wa_btn.setFixedHeight(32)
        wa_btn.clicked.connect(self.copy_whatsapp_pitch)
        row.addWidget(wa_btn)

        reset_btn = QPushButton("Reset (Ctrl+N)")
        reset_btn.setObjectName("Ghost")
        reset_btn.setFixedHeight(32)
        reset_btn.clicked.connect(self.reset_scan)
        reset_btn.setShortcut("Ctrl+N")
        reset_btn.setToolTip("Re-run the benchmark (Ctrl+N)")
        row.addWidget(reset_btn)

        return footer

    # ---------------------------------------------------------------- Navigation / Actions
    def select_rail_item(self, key: str) -> None:
        self.selected = key
        for k, item in self.rail_items.items():
            item.set_selected(k == key)
        if key == VERDICT_ROW:
            self._render_default_evidence_deck()
        elif key == "interactive":
            self._render_interactive_panel()
        else:
            self._show_check_details(key)

    def _show_check_details(self, key: str) -> None:
        _clear(self.detail_layout)
        check = self.report.check(key) if self.report else None
        if not check:
            self._render_default_evidence_deck()
            return

        head = QHBoxLayout()
        title = QLabel(check.label.upper())
        title.setStyleSheet("font-size: 15.5px; font-weight: 800; color: #FFFFFF;")
        head.addWidget(title)
        head.addStretch(1)
        score_lbl = QLabel(f"{check.score:.0f}/100" if check.scored else "unscored")
        score_lbl.setObjectName("BadgeGreen" if check.score >= 80
                                else "BadgeAmber" if check.score >= 50 else "BadgeRed")
        head.addWidget(score_lbl)
        self.detail_layout.addLayout(head)

        summary = QLabel(check.summary or check.status)
        summary.setWordWrap(True)
        summary.setStyleSheet("color: #BCC8D6; font-size: 14.5px;")
        self.detail_layout.addWidget(summary)

        if check.error:
            err = QLabel(check.error)
            err.setWordWrap(True)
            err.setStyleSheet("color: #F59E0B; font-size: 13.5px;")
            self.detail_layout.addWidget(err)

        # One card per physical drive, worst first, before the findings: the
        # SSD and the HDD were being merged into one block of numbers.
        if key == "storage":
            drives = ((check.data or {}).get("drives") or [])
            ordered = sorted(drives, key=_drive_badness, reverse=True)
            for drive in ordered:
                card = SmartRegistersWidget()
                card.set_drive(drive)
                self.detail_layout.addWidget(card)

        if key == "peripherals":
            self.detail_layout.addWidget(self._device_list(check))

        order = {"critical": 0, "major": 1, "warn": 2, "info": 3}
        if check.findings:
            for finding in sorted(check.findings,
                                  key=lambda f: (-int(f.blocking),
                                                 order.get(f.severity, 9))):
                self.detail_layout.addWidget(self._finding_card(check, finding))
        else:
            ok_box = QFrame()
            ok_box.setObjectName("Card")
            ok_box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            ok_l = QVBoxLayout(ok_box)
            ok_l.setContentsMargins(14, 12, 14, 12)
            ok_lbl = QLabel(f"✓ {check.label}: no defects found by this check.")
            ok_lbl.setStyleSheet("color: #10B981; font-weight: 700; font-size: 15px;")
            ok_l.addWidget(ok_lbl)
            self.detail_layout.addWidget(ok_box)

        # Telemetry only where it belongs, and only from real data
        if key == "thermal":
            gpu = self.report.check("gpu") if self.report else None
            waterfall = SensorWaterfallWidget()
            waterfall.set_data(check.data or {}, self.report.machine,
                               (gpu.data if gpu else {}) or {})
            self.detail_layout.addWidget(waterfall)

        self.detail_layout.addStretch(1)

    # ------------------------------------------------------------ v2 interactive
    def _render_interactive_panel(self) -> None:
        _clear(self.detail_layout)
        self.interactive_panel = InteractivePanel(
            self.interactive_results, self._run_interactive, self._clear_interactive,
            stress=self._stress_state())
        self.detail_layout.addWidget(self.interactive_panel)

        check = self.report.check("interactive") if self.report else None
        if check and check.findings:
            head = QLabel("RESULTS")
            head.setStyleSheet("font-size: 13px; font-weight: 800; color: #8593A6;"
                               " letter-spacing: 1px; margin-top: 8px;")
            self.detail_layout.addWidget(head)
            order = {"critical": 0, "major": 1, "warn": 2, "info": 3}
            for finding in sorted(check.findings,
                                  key=lambda f: order.get(f.severity, 9)):
                self.detail_layout.addWidget(self._finding_card(check, finding))

        self.detail_layout.addStretch(1)

    def _run_interactive(self, key: str) -> None:
        if key in ("cpu", "gpu"):
            self._open_stress_lab()
            return
        result: Dict[str, object] = {}
        if key == "screen":
            from .tests.screen_test import ScreenTestDialog
            dialog = ScreenTestDialog(self)
            dialog.start()
            dialog.exec()
            result = dialog.result
        elif key == "keyboard":
            from .tests.keyboard_test import KeyboardTestDialog
            dialog = KeyboardTestDialog(self)
            dialog.exec()
            result = dialog.result
        else:
            from .tests.port_test import PortTestDialog
            machine = self.report.machine if self.report else None
            dialog = PortTestDialog(machine, self)
            dialog.exec()
            result = dialog.result

        if not result.get("run"):
            return
        self.interactive_results[key] = result
        self._apply_interactive()

    def _apply_interactive(self) -> None:
        if not self.report:
            QMessageBox.information(
                self, "No scan yet",
                "Run a benchmark first - the interactive results are scored "
                "against the machine the scan found.")
            return

        from ..engine.checks import interactive as interactive_check
        from ..engine.inspector import Inspector

        check = interactive_check.build_check(self.interactive_results)
        self.report.checks = [c for c in self.report.checks if c.key != "interactive"]
        self.report.checks.append(check)

        options = Options(asking_price_pkr=self.asking.value() or None,
                          market_price_pkr=self.market.value() or None,
                          claims=self._claims())
        Inspector(options).finalise(self.report)
        self.on_report(self.report)

    def _clear_interactive(self) -> None:
        self.interactive_results = {}
        if self.report:
            self.report.checks = [c for c in self.report.checks
                                  if c.key != "interactive"]
            from ..engine.inspector import Inspector
            options = Options(asking_price_pkr=self.asking.value() or None,
                              market_price_pkr=self.market.value() or None,
                              claims=self._claims())
            Inspector(options).finalise(self.report)
            self.on_report(self.report)
        self.select_rail_item("interactive")

    # ------------------------------------------------------------- stress lab
    def _stress_state(self) -> Dict[str, Dict[str, Any]]:
        """The load-test results already in the report, for the panel badges."""
        if not self.report:
            return {}
        thermal = self.report.check("thermal")
        gpu = self.report.check("gpu")
        return {
            "cpu": (thermal.data if thermal and thermal.data else None),
            "gpu": ((gpu.data or {}).get("stress") if gpu else None),
        }

    def _open_stress_lab(self) -> None:
        from .tests.stress_lab import StressLabDialog

        state = self._stress_state()
        dialog = StressLabDialog(state.get("cpu"), state.get("gpu"), self)
        dialog.exec()

        if not dialog.cpu_ran and not dialog.gpu_ran:
            return
        self._apply_stress(
            cpu=dialog.cpu_result if dialog.cpu_ran else None,
            gpu=dialog.gpu_result if dialog.gpu_ran else None)

    def _apply_stress(self, cpu: Optional[Dict[str, Any]] = None,
                      gpu: Optional[Dict[str, Any]] = None) -> None:
        """Fold a hand-run load test back into the report and rescore it."""
        if not self.report:
            QMessageBox.information(
                self, "No scan yet",
                "Run a benchmark first - the load test is scored against the "
                "machine the scan found.")
            return

        from ..engine.inspector import Inspector

        if cpu:
            from ..engine.checks import thermal as thermal_check
            rebuilt = thermal_check.from_probe(cpu)
            self.report.checks = [c for c in self.report.checks
                                  if c.key != "thermal"] + [rebuilt]
        if gpu:
            from ..engine.checks import gpu as gpu_check
            existing = self.report.check("gpu")
            if existing is not None:
                gpu_check.apply_stress(existing, gpu)

        options = Options(asking_price_pkr=self.asking.value() or None,
                          market_price_pkr=self.market.value() or None,
                          claims=self._claims())
        Inspector(options).finalise(self.report)
        self.selected = "interactive"
        self.on_report(self.report)

    # ---------------------------------------------------------------- Scanning & Reports
    def _claims(self) -> Dict[str, object]:
        claims: Dict[str, object] = {}
        if self.claim_cpu.text().strip():
            claims["cpu"] = self.claim_cpu.text().strip()
        for key, widget in (("ram_gb", self.claim_ram), ("storage_gb", self.claim_disk)):
            text = widget.text().strip()
            if text:
                try:
                    claims[key] = float(text)
                except ValueError:
                    pass
        kind = self.claim_type.currentText()
        if kind and kind != "any":
            claims["storage_type"] = kind
        if self.claim_gpu.text().strip():
            claims["gpu"] = self.claim_gpu.text().strip()
        return claims

    def start_scan(self) -> None:
        if self._scanning:
            return
        from .worker import InspectionWorker

        options = Options(
            thermal_seconds=float(self.thermal_seconds.value()),
            skip_thermal=False,
            fast=self.fast_mode.isChecked(),
            claims=self._claims(),
            asking_price_pkr=self.asking.value() or None,
            market_price_pkr=self.market.value() or None,
        )
        self._scanning = True
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("Probing...")
        self.status_lbl.setText("Reading firmware, SMART registers and thermal sensors...")

        self.worker = InspectionWorker(options, self)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_report.connect(self.on_report)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_finished(self) -> None:
        self._scanning = False
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("⚡ Run Full Benchmark")

    def on_progress(self, key: str, fraction: float, text: str) -> None:
        self.status_lbl.setText(f"Probing {key}: {text or ''}")

    def _badge_for(self, check: R.CheckResult) -> tuple:
        """Rail badge from the check's own data, never a fixed string."""
        d = check.data or {}
        style = {"ok": "BadgeGreen", "warn": "BadgeAmber",
                 "fail": "BadgeRed"}.get(check.status, "BadgeDark")

        if check.key == "thermal":
            temps = [t for t in (d.get("temps_c") or []) if isinstance(t, (int, float))]
            if temps:
                return f"{max(temps):.0f}°C", style
            sag = d.get("sag_ratio")
            if sag:
                return f"{sag * 100:.0f}% peak", style
            return "no sensor", style

        if check.key == "battery":
            design, full = d.get("design_mwh"), d.get("full_mwh")
            if design and full:
                return f"{round(full / design * 100)}%", style
            if check.status == "fail":
                return "dead", style
            return "n/a", style

        if check.key == "storage":
            drives = d.get("drives") or []
            pending = sum((dr.get("smart") or {}).get("pending") or 0 for dr in drives)
            if pending:
                return f"{pending} pending", "BadgeRed"
            if not drives:
                return "no access", "BadgeDark"
            if check.status == "fail":
                return "FAILING", "BadgeRed"
            if check.status == "warn":
                return "WARN", "BadgeAmber"
            return f"{check.score:.0f}", "BadgeGreen"

        if check.key == "dgpu":
            if d.get("discrete"):
                return "present", "BadgeGreen"
            if d.get("expected"):
                return "missing", "BadgeRed"
            return "n/a", "BadgeDark"

        if check.key == "specs":
            ram = (d.get("ram") or {}).get("installed_gb")
            return (f"{ram:g}GB" if ram else "?"), style

        if check.key == "gpu":
            tdr = d.get("tdr_count") or 0
            if tdr:
                return f"{tdr} TDR", "BadgeRed"
            return f"{check.score:.0f}", style

        if check.key == "peripherals":
            present = d.get("present") or {}
            broken = len(d.get("broken") or [])
            if broken:
                return f"{broken} broken", "BadgeRed"
            radios = [k for k in ("wifi", "bluetooth") if present.get(k)]
            if radios:
                return f"{len(radios)} radio(s)", "BadgeGreen"
            return "none", "BadgeDark"

        return (f"{check.score:.0f}" if check.scored else "--"), style

    def on_report(self, report: R.Report) -> None:
        self.report = report
        self._scanning = False
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("⚡ Run Full Benchmark")

        m = report.machine
        maker = (m.get("manufacturer") or "").strip()
        if maker.isupper():
            maker = maker.title()
        title = " ".join(x for x in [maker, m.get("family") or m.get("model")] if x)
        cpu = (m.get("cpu") or "").replace("(R)", "").replace("(TM)", "").strip()
        self.chip_label.setText(
            f"{title} · {cpu[:26]} · {m.get('ram_gb', '?')}GB"
            if title else "No machine scanned")
        self.rail_header.name_lbl.setText(f"{cpu[:22] or 'Unknown'} · {m.get('ram_gb', '?')}GB")
        health_colour = theme.VERDICT.get(report.verdict, theme.GREY)
        self.rail_header.health_lbl.setText(
            f"Health Index: {report.score:.0f}/100 ({report.verdict})")
        self.rail_header.health_lbl.setStyleSheet(
            f"font-size: 13.5px; color: {health_colour}; font-weight: 600;")

        if report.admin:
            self.admin_pill.setText("Admin · SMART direct")
            self.admin_pill.setObjectName("BadgeGreen")
        else:
            self.admin_pill.setText("No admin · SMART blocked")
            self.admin_pill.setObjectName("BadgeAmber")
        self.admin_pill.style().unpolish(self.admin_pill)
        self.admin_pill.style().polish(self.admin_pill)

        # A report carries the claims it was scanned with. Put them back into the
        # panel, but never overwrite a field the buyer is part-way through
        # editing - on_report also runs on every reprice.
        claims = report.claims or {}
        for widget, key, cast in ((self.claim_cpu, "cpu", str),
                                  (self.claim_ram, "ram_gb", str),
                                  (self.claim_disk, "storage_gb", str),
                                  (self.claim_gpu, "gpu", str)):
            value = claims.get(key)
            if value not in (None, "") and not widget.text().strip():
                widget.setText(cast(value))
        if claims.get("storage_type") and self.claim_type.currentIndex() == 0:
            index = self.claim_type.findText(str(claims["storage_type"]))
            if index > 0:
                self.claim_type.setCurrentIndex(index)
        if (report.negotiation.asking_price_pkr
                and not self.asking.value()):
            self.asking.blockSignals(True)
            self.asking.setValue(int(report.negotiation.asking_price_pkr))
            self.asking.blockSignals(False)

        self.ribbon.update_matrix(self._claims(), m, report.negotiation.asking_price_pkr)

        reasons_summary = " · ".join(report.verdict_reasons)[:110] or "Hardware health verified"
        self.card_verdict.update_verdict(report.score, report.verdict, reasons_summary)

        neg = report.negotiation
        if neg.asking_price_pkr:
            self.card_quoted.set_content(f"{neg.asking_price_pkr:,} PKR",
                                         "seller's asking price", theme.TEXT)
        else:
            self.card_quoted.set_content("not given", "enter it under Claims",
                                         theme.TEXT_DIM)

        if neg.items:
            top = " + ".join(f"{i['cost_pkr'] // 1000}k" for i in neg.items[:3])
            self.card_repair.set_content(
                f"-{neg.total_repair_pkr:,} PKR",
                f"{len(neg.items)} defect(s): {top}", theme.RED)
        else:
            self.card_repair.set_content("0 PKR", "no repairable defects", theme.GREEN)

        buf = int(neg.total_repair_pkr * 0.10)
        self.card_buffer.set_content(f"-{buf:,} PKR" if buf else "0 PKR",
                                     "10% risk allowance", theme.TEXT_DIM)

        # The offer comes from what the machine is worth, not from what the
        # seller asks, so it does not move when the asking price moves.
        if neg.walk_away and not neg.suggested_offer_pkr:
            self.card_offer.set_content(
                "Don't buy", neg.walk_away_reason or "blocking defect", theme.RED)
        elif neg.suggested_offer_pkr is not None:
            if neg.price_basis == "market" and neg.market_price_pkr:
                basis = (f"market {neg.market_price_pkr:,}"
                         f" − repairs {neg.total_repair_pkr:,}")
            else:
                basis = f"asking − repairs {neg.total_repair_pkr:,}"
            self.card_offer.set_content(
                f"{neg.suggested_offer_pkr:,} PKR",
                basis + (f" · {neg.walk_away_reason}" if neg.walk_away_reason else ""),
                theme.GREEN if not neg.walk_away else theme.AMBER)
        else:
            self.card_offer.set_content("No offer yet",
                                        "set the market price in Claims",
                                        theme.AMBER)

        for c in report.checks:
            item = self.rail_items.get(c.key)
            if item:
                text, style = self._badge_for(c)
                item.set_badge(text, style)

        if VERDICT_ROW in self.rail_items:
            self.rail_items[VERDICT_ROW].set_badge(
                f"{report.score:.0f}",
                "BadgeRed" if report.verdict == "WALK AWAY"
                else "BadgeGreen" if report.verdict == "BUY" else "BadgeAmber")

        # Real tamper-evident digest of the report, not a decorative string
        digest = hashlib.sha256(
            json.dumps(report.to_dict(), sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        self.status_lbl.setText(
            f"Scan {report.duration_s:.0f}s · {report.generated_at[:19]} · "
            f"SHA256 {digest[:8]}…{digest[-4:]}")

        # A scan with no asking price cannot produce a counter-offer. Open the
        # panel once so the field is on screen instead of hidden behind a button.
        if not neg.asking_price_pkr and not self._claims_auto_shown:
            self._claims_auto_shown = True
            self.claims_toggle.setChecked(True)

        # Re-render whatever pane is open so it picks up the new report. Without
        # this the detail stage keeps showing the pre-scan empty state.
        self.select_rail_item(self.selected)

    def on_failed(self, msg: str) -> None:
        self._scanning = False
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("⚡ Run Full Benchmark")
        self.status_lbl.setText("Benchmark encountered an exception")

    def reset_scan(self) -> None:
        self.start_scan()

    def copy_whatsapp_pitch(self) -> None:
        if not self.report:
            QMessageBox.information(
                self, "No scan yet",
                "Run a benchmark first - the counter-offer script is built from "
                "what was actually measured.")
            return

        report = self.report
        m = report.machine
        neg = report.negotiation
        model_name = m.get("family") or m.get("model") or "Laptop"

        lines = [
            f"Salam bhai, {model_name} laptop check kiya hai diagnostic audit tool se.",
            f"Health Score: {report.score:.0f}/100 ({report.verdict})",
            "",
            "Hardware Verification & Defects:",
        ]
        pairs = self._all_findings()
        actionable = [(c, f) for c, f in pairs if f.severity in ("critical", "major", "warn")]
        if actionable:
            for index, (check, finding) in enumerate(actionable[:5], start=1):
                cost = f" (Cost: -{finding.cost_pkr:,} PKR)" if finding.cost_pkr else ""
                lines.append(f"{index}. {check.label}: {finding.title}{cost}")
        else:
            lines.append("No defects found by the scan.")

        lines.append("")
        if neg.total_repair_pkr:
            lines.append(f"Total Repair Exposure: -{neg.total_repair_pkr:,} PKR")
        if neg.asking_price_pkr:
            lines.append(f"Quoted Asking: {neg.asking_price_pkr:,} PKR")
        if neg.suggested_offer_pkr is not None:
            lines.append(f"Recommended Counter-Offer: {neg.suggested_offer_pkr:,} PKR (Cash deal)")
        else:
            lines.append(f"Deduct {neg.total_repair_pkr:,} PKR from the asking price.")
        lines.append("")
        lines.append("Aap check kar lein, is offer pe deal ban sakti hai.")

        pitch = "\n".join(lines)
        QApplication.clipboard().setText(pitch)
        self.status_lbl.setText("✓ Counter-offer script copied to clipboard")
        QMessageBox.information(
            self, "Counter-Offer Script Copied",
            "Built from this scan's actual findings, copied to your clipboard:\n\n" + pitch)

    def export(self, kind: str) -> None:
        if not self.report:
            QMessageBox.information(self, "Export", "Please run a scan before exporting evidence.")
            return
        m = self.report.machine
        stem = (m.get("family") or m.get("model") or "laptop").replace(" ", "-").lower()
        stamp = self.report.generated_at[:10]
        default = os.path.join(os.path.expanduser("~"), "Desktop", f"{stem}-inspection-{stamp}.{kind}")
        filters = {"pdf": "PDF report (*.pdf)", "json": "JSON (*.json)", "html": "HTML report (*.html)"}
        path, _ = QFileDialog.getSaveFileName(self, "Save Inspection Evidence", default, filters[kind])
        if not path:
            return
        try:
            if kind == "pdf":
                pdf_report.build(self.report, path)
            elif kind == "json":
                json_report.write(self.report, path)
            else:
                html_report.write(self.report, path)
            self.status_lbl.setText(f"Evidence exported to {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))
