"""The one-page PDF report.

Layout order is deliberate: verdict, then what it costs to fix, then the evidence.
A buyer at a counter reads top-down and stops when they have what they need.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..engine import result as R
from ..scoring import rubric
from .pdf_canvas import A4, PdfCanvas, text_width

# ---- palette
INK = (0.10, 0.13, 0.17)
NAVY = (0.07, 0.10, 0.15)
GREY = (0.42, 0.45, 0.50)
LIGHT = (0.93, 0.94, 0.95)
RULE = (0.82, 0.84, 0.86)
WHITE = (1, 1, 1)
GREEN = (0.11, 0.53, 0.33)
AMBER = (0.79, 0.54, 0.00)
RED = (0.77, 0.16, 0.16)
BLUE = (0.13, 0.35, 0.62)

SEV_COLOUR = {
    R.CRITICAL: RED,
    R.MAJOR: (0.85, 0.42, 0.10),
    R.WARN: AMBER,
    R.INFO: BLUE,
}

MARGIN = 36.0
CONTENT_W = A4[0] - 2 * MARGIN


def _pkr(value: Optional[int]) -> str:
    if value is None:
        return "-"
    return f"{int(value):,} PKR"


def _rgb(hex_colour: str) -> Tuple[float, float, float]:
    """rubric speaks hex, the canvas speaks 0..1 floats."""
    h = (hex_colour or "#555555").lstrip("#")
    if len(h) != 6:
        return (0.33, 0.33, 0.33)
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _sev_label(sev: str) -> str:
    return {"critical": "CRITICAL", "major": "MAJOR",
            "warn": "WARN", "info": "INFO"}.get(sev, sev.upper())


class _Flow:
    def __init__(self, pdf: PdfCanvas) -> None:
        self.pdf = pdf
        self.y = MARGIN
        self.page = 1

    def ensure(self, height: float, header: str = "") -> None:
        if self.y + height > A4[1] - 52:
            self.pdf.add_page()
            self.page += 1
            self.y = MARGIN
            if header:
                self.pdf.text(MARGIN, self.y, header, 7.5, True, GREY)
                self.y += 14
                self.pdf.line(MARGIN, self.y, A4[0] - MARGIN, self.y, RULE, 0.5)
                self.y += 12

    def section(self, title: str) -> None:
        self.ensure(34, title)
        self.y += 8
        self.pdf.text(MARGIN, self.y + 8, title.upper(), 8, True, NAVY)
        self.pdf.line(MARGIN, self.y + 13, A4[0] - MARGIN, self.y + 13, NAVY, 0.9)
        self.y += 22


def _header(pdf: PdfCanvas, report: R.Report) -> None:
    pdf.rect(0, 0, A4[0], 92, fill=NAVY)
    m = report.machine
    maker = (m.get("manufacturer") or "").strip()
    if maker.isupper():
        maker = maker.title()
    brand = " ".join(x for x in [maker, m.get("family") or m.get("model")] if x)
    brand = brand.strip() or "Unknown machine"

    pdf.text(MARGIN, 24, "USED LAPTOP INSPECTOR", 7.5, True, (0.55, 0.62, 0.72))
    pdf.text(MARGIN, 44, pdf.truncate(brand, CONTENT_W - 170, 17, True), 17, True, WHITE)

    bits = []
    if m.get("cpu"):
        bits.append(str(m["cpu"]).replace("(R)", "").replace("(TM)", "")
                    .replace("CPU ", "").strip())
    if m.get("ram_gb"):
        bits.append(f"{m['ram_gb']:g} GB RAM")
    if m.get("storage"):
        d = m["storage"][0]
        bits.append(f"{d.get('size_gb') or '?'} GB {d.get('bus') or ''}".strip())
    if m.get("gpus"):
        bits.append(str(m["gpus"][0])[:38])
    pdf.text(MARGIN, 62, pdf.truncate("  |  ".join(bits), CONTENT_W - 170, 8), 8,
             False, (0.68, 0.74, 0.82))
    if m.get("serial"):
        pdf.text(MARGIN, 76, f"Serial {m['serial']}", 7.5, False, (0.52, 0.58, 0.68))

    # verdict badge
    colour = _rgb(rubric.verdict_colour(report.verdict))
    badge_w = 150.0
    bx = A4[0] - MARGIN - badge_w
    pdf.rect(bx, 22, badge_w, 50, fill=colour)
    pdf.text_center(bx + badge_w / 2, 42, report.verdict, 15, True, WHITE)
    pdf.text_center(bx + badge_w / 2, 60, f"{report.score:.0f} / 100", 10, True,
                    (1, 1, 1))
    pdf.rect(bx, 22, badge_w, 2.5, fill=WHITE)


def _verdict_block(flow: _Flow, report: R.Report) -> None:
    pdf = flow.pdf
    flow.y = 106
    reasons = report.verdict_reasons or []
    for reason in reasons[:3]:
        for i, line in enumerate(pdf.wrap(reason, CONTENT_W - 10, 8.5)):
            pdf.text(MARGIN + (0 if i == 0 else 8), flow.y,
                     ("- " if i == 0 else "") + line, 8.5, False, INK)
            flow.y += 10.5
    flow.y += 3


def _score_table(flow: _Flow, report: R.Report) -> None:
    pdf = flow.pdf
    breakdown = (report.extras.get("score_breakdown") or [])
    if not breakdown:
        return
    flow.section("Score breakdown")
    row_h = 15.0
    col = [MARGIN, MARGIN + 150, MARGIN + 195, MARGIN + 250, MARGIN + 470]
    pdf.text(col[0], flow.y, "CHECK", 6.8, True, GREY)
    pdf.text_right(col[2], flow.y, "SCORE", 6.8, True, GREY)
    pdf.text_right(col[3], flow.y, "WEIGHT", 6.8, True, GREY)
    pdf.text(col[4], flow.y, "STATUS", 6.8, True, GREY)
    flow.y += 6
    pdf.line(MARGIN, flow.y, A4[0] - MARGIN, flow.y, RULE, 0.5)
    flow.y += 10

    for item in breakdown:
        flow.ensure(row_h)
        score = item.get("score") or 0
        status = item.get("status") or ""
        measured = bool(item.get("effective_weight"))
        label = pdf.truncate(item.get("label", ""), 140, 8.2)
        pdf.text(col[0], flow.y, label, 8.2, False, INK)
        pdf.text_right(col[2], flow.y, f"{score:.0f}" if measured else "-", 8.2,
                       measured, INK)
        weight = item.get("effective_weight")
        pdf.text_right(col[3], flow.y, f"{weight:.0f}" if weight else "-", 8.2,
                       False, GREY)
        bar_x = col[3] + 14
        bar_w = 120.0
        pdf.rect(bar_x, flow.y - 5, bar_w, 6, fill=(0.88, 0.89, 0.90))
        filled = bar_w * max(0.0, min(1.0, score / 100.0))
        bar_colour = GREEN if score >= 80 else AMBER if score >= 55 else RED
        if item.get("effective_weight"):
            pdf.rect(bar_x, flow.y - 5, filled, 6, fill=bar_colour)
        pdf.text(bar_x + bar_w + 10, flow.y, status.upper(), 6.8, False, GREY)
        flow.y += row_h


def _negotiation(flow: _Flow, report: R.Report) -> None:
    pdf = flow.pdf
    neg = report.negotiation
    flow.section("What it costs to put right")

    if not neg.items:
        flow.ensure(24)
        pdf.text(MARGIN, flow.y, "No repairable defects found.", 8.5, False, INK)
        flow.y += 16
        if neg.advice:
            for line in pdf.wrap(neg.advice, CONTENT_W, 8.2)[:3]:
                pdf.text(MARGIN, flow.y, line, 8.2, False, GREY)
                flow.y += 10
        return

    for item in neg.items[:8]:
        flow.ensure(13)
        sev = item.get("severity")
        colour = SEV_COLOUR.get(sev, GREY)
        pdf.rect(MARGIN, flow.y - 5.5, 3, 9, fill=colour)
        title = pdf.truncate(item["title"], CONTENT_W - 130, 8.2)
        pdf.text(MARGIN + 8, flow.y, title, 8.2, False, INK)
        pdf.text_right(A4[0] - MARGIN, flow.y, _pkr(item["cost_pkr"]), 8.2, True, INK)
        flow.y += 12.5

    flow.ensure(30)
    pdf.line(MARGIN, flow.y - 3, A4[0] - MARGIN, flow.y - 3, RULE, 0.7)
    flow.y += 9
    pdf.text(MARGIN, flow.y, "Total repair exposure", 8.6, True, INK)
    pdf.text_right(A4[0] - MARGIN, flow.y, _pkr(neg.total_repair_pkr), 9.2, True, INK)
    flow.y += 18

    # offer box
    box_h = 30.0
    flow.ensure(box_h + 8)
    colour = RED if neg.walk_away else GREEN
    pdf.rect(MARGIN, flow.y - 6, CONTENT_W, box_h, fill=(0.96, 0.97, 0.98),
             stroke=colour, lw=1.0)
    # The offer is built from what the machine is worth, so it exists even when
    # the seller has not named a price. The basis is printed on the line above it
    # so the number can be checked instead of trusted.
    basis = ""
    if neg.price_basis == "market" and neg.market_price_pkr:
        basis = (f"market {_pkr(neg.market_price_pkr)}"
                 f" - repairs {_pkr(neg.total_repair_pkr)}")
    left = f"Asking {_pkr(neg.asking_price_pkr)}" if neg.asking_price_pkr else basis
    if left:
        pdf.text(MARGIN + 10, flow.y + 5, left, 8, False, GREY)
    if neg.suggested_offer_pkr is not None:
        pdf.text(MARGIN + 10, flow.y + 18,
                 f"Offer {_pkr(neg.suggested_offer_pkr)}", 11, True, colour)
        if neg.max_offer_pkr is not None:
            pdf.text_right(A4[0] - MARGIN - 10, flow.y + 18,
                           f"ceiling {_pkr(neg.max_offer_pkr)}", 8.5, False, GREY)
    elif neg.asking_price_pkr:
        pdf.text(MARGIN + 10, flow.y + 18, "Walk away", 11, True, colour)
    else:
        pdf.text(MARGIN + 10, flow.y + 18,
                 f"Deduct {_pkr(neg.total_repair_pkr)} from the price", 10.5, True,
                 colour)
    flow.y += box_h + 6

    if neg.advice:
        for line in pdf.wrap(neg.advice, CONTENT_W, 8.0)[:4]:
            flow.ensure(10)
            pdf.text(MARGIN, flow.y, line, 8.0, False, INK)
            flow.y += 9.8


def _findings(flow: _Flow, report: R.Report) -> None:
    pdf = flow.pdf
    items: List[Tuple[str, R.Finding]] = []
    order = {R.CRITICAL: 0, R.MAJOR: 1, R.WARN: 2, R.INFO: 3}
    for check in report.checks:
        for f in check.findings:
            items.append((check.label, f))
    items.sort(key=lambda pair: (order.get(pair[1].severity, 9),
                                 -int(pair[1].blocking)))
    if not items:
        return

    flow.section("Findings")
    for label, f in items[:8]:
        detail = f.detail or ""
        lines = pdf.wrap(detail, CONTENT_W - 12, 7.6) if detail else []
        block_h = 12 + min(len(lines), 1) * 9.2
        flow.ensure(block_h)
        colour = SEV_COLOUR.get(f.severity, GREY)
        pdf.rect(MARGIN, flow.y - 5.5, 3, 9.5, fill=colour)
        pdf.text(MARGIN + 8, flow.y, pdf.truncate(f.title, CONTENT_W - 100, 8.4),
                 8.4, True, INK)
        pdf.text_right(A4[0] - MARGIN, flow.y, _sev_label(f.severity), 6.6, True,
                       colour)
        flow.y += 10.5
        for line in lines[:1]:
            pdf.text(MARGIN + 8, flow.y, line, 7.6, False, GREY)
            flow.y += 9.2
        flow.y += 1.5


def _evidence(flow: _Flow, report: R.Report) -> None:
    """The numbers behind the score. Never a bare number."""
    pdf = flow.pdf
    rows: List[Tuple[str, str]] = []
    for check in report.checks:
        d = check.data or {}
        if check.key == "specs":
            screen = d.get("screen") or {}
            if screen.get("resolution"):
                rows.append(("Display", f"{screen['resolution']} @ {screen.get('refresh_hz') or '?'} Hz"))
            bios = d.get("bios") or {}
            if bios.get("version"):
                rows.append(("BIOS", f"{bios['version']} ({bios.get('date') or '?'})"))
            rows.append(("OEM key", d.get("oem_key") or "not in firmware"))
        elif check.key == "battery":
            if d.get("design_mwh") and d.get("full_mwh"):
                rows.append(("Battery", f"{d['full_mwh']} / {d['design_mwh']} mWh, "
                                        f"{d.get('cycle_count') or '?'} cycles"))
            else:
                rows.append(("Battery", "capacity not reported"))
        elif check.key == "storage":
            for drive in (d.get("drives") or [])[:2]:
                smart = drive.get("smart") or {}
                bits = []
                if smart.get("power_on_hours"):
                    bits.append(f"{smart['power_on_hours']:,} h")
                if smart.get("wear_pct") is not None:
                    bits.append(f"{smart['wear_pct']}% worn")
                if smart.get("reallocated"):
                    bits.append(f"{smart['reallocated']} realloc")
                if smart.get("pending"):
                    bits.append(f"{smart['pending']} pending")
                rows.append((drive.get("model") or f"Disk {drive.get('index')}",
                             ", ".join(bits) or "SMART unreadable"))
        elif check.key == "thermal":
            if d.get("peak_mhz"):
                rows.append(("CPU load", f"{d['peak_mhz']:.0f} -> "
                                         f"{d.get('sustained_mhz') or 0:.0f} MHz, "
                                         f"{(d.get('sag_ratio') or 1) * 100:.0f}% held"))
        elif check.key == "gpu":
            rows.append(("Driver resets", str(d.get("tdr_count") or 0) + " in 180 d"))
            stress = d.get("stress") or {}
            if stress.get("available"):
                rate = stress.get("frames_per_sec") or 0
                rows.append(("GPU load", f"{rate:,} frames/s, "
                                         f"FL {stress.get('feature_level')}"))
        elif check.key == "dgpu":
            matched = d.get("matched_model") or {}
            if matched:
                rows.append(("Factory GPU", ", ".join(d.get("expected") or ["none"])))

    if not rows:
        return
    flow.section("Evidence")
    for label, value in rows[:7]:
        flow.ensure(11)
        pdf.text(MARGIN, flow.y, pdf.truncate(label, 150, 7.8), 7.8, False, GREY)
        pdf.text(MARGIN + 160, flow.y, pdf.truncate(value, CONTENT_W - 160, 7.8),
                 7.8, False, INK)
        flow.y += 10.5


def _footer(pdf: PdfCanvas, report: R.Report) -> None:
    y = A4[1] - 30
    pdf.line(MARGIN, y - 6, A4[0] - MARGIN, y - 6, RULE, 0.5)
    pdf.text(MARGIN, y + 2,
             f"Generated {report.generated_at[:19]}  |  v{report.tool_version}  |  "
             f"offline, no telemetry", 6.8, False, GREY)
    pdf.text_right(A4[0] - MARGIN, y + 2,
                   "Evidence is shown for every score. Verify anything you plan to "
                   "argue about.", 6.8, False, GREY)


def build(report: R.Report, path: str) -> str:
    pdf = PdfCanvas(path, A4)
    _header(pdf, report)
    flow = _Flow(pdf)
    _verdict_block(flow, report)
    _score_table(flow, report)
    _negotiation(flow, report)
    _findings(flow, report)
    _evidence(flow, report)
    _footer(pdf, report)
    return pdf.save()
