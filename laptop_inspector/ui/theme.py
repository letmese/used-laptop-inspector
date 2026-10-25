"""Dark Fluent Telemetry theme for Used Laptop Inspector.

Matches the Windows 11 Fluent Design System specifications from Stitch:
- Deep obsidian mica base (#090B10 / #0B0E14)
- Layered acrylic tiers (#11141D, #161B26, #1C2230)
- High-visibility semantic signals (Emerald #10B981, Amber #F59E0B, Crimson #EF4444)
- Technical telemetry accents (Electric Blue #3B82F6, Cyan #06B6D4, Neon Pink/Red #F43F5E)
- Monospaced JetBrains/Cascadia typography for telemetry registers and PKR currencies
"""

from __future__ import annotations

# Core Palette
BASE = "#090B10"
CANVAS = "#0B0E14"
SURFACE = "#11141D"
SURFACE_2 = "#161B26"
SURFACE_3 = "#1C2230"
SURFACE_CARD = "#141923"

BORDER = "#222938"
BORDER_SOFT = "#181E2B"
BORDER_ACTIVE = "#3B82F6"

TEXT = "#F1F5F9"
TEXT_DIM = "#BCC8D6"
TEXT_FAINT = "#7E8DA2"

ACCENT = "#3B82F6"
CYAN = "#06B6D4"

GREEN = "#10B981"
AMBER = "#F59E0B"
ORANGE = "#FB923C"
RED = "#EF4444"
PINK = "#F43F5E"
BLUE = "#3B82F6"
GREY = "#8FA0B4"

# Legacy aliases kept for engine compatibility
BG = BASE
PANEL = SURFACE
PANEL_ALT = SURFACE_2
MUTED = TEXT_DIM

SEVERITY = {
    "critical": RED,
    "major": CYAN,
    "warn": AMBER,
    "info": BLUE,
}

VERDICT = {
    "BUY": GREEN,
    "NEGOTIATE": AMBER,
    "WALK AWAY": RED,
}

STATUS_COLOUR = {
    "ok": GREEN,
    "warn": AMBER,
    "fail": RED,
    "unavailable": GREY,
    "error": RED,
}


def verdict_tint(verdict: str) -> tuple:
    """(start, end) for the hero gradient - verdict colour fading into the base."""
    return {
        "BUY": ("#062A1B", "#11141D"),
        "NEGOTIATE": ("#2B1F0A", "#11141D"),
        "WALK AWAY": ("#320D12", "#11141D"),
    }.get(verdict, (SURFACE_2, SURFACE))


STYLESHEET = f"""
* {{
    font-family: "Segoe UI Variable Display", "Segoe UI", "Inter", sans-serif;
    font-size: 15.5px;
    color: {TEXT};
}}

QMainWindow, QDialog {{
    background-color: {BASE};
}}

QWidget#Root {{
    background-color: {BASE};
}}

QScrollArea, QScrollArea > QWidget > QWidget {{
    background-color: transparent;
}}

QScrollArea {{
    border: none;
}}

QScrollBar:vertical {{
    background-color: transparent;
    width: 6px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background-color: #1F2837;
    min-height: 24px;
    border-radius: 3px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: #313F54;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}

QScrollBar:horizontal {{
    background-color: transparent;
    height: 6px;
}}
QScrollBar::handle:horizontal {{
    background-color: #1F2837;
    border-radius: 3px;
}}

QLabel {{
    background-color: transparent;
}}

QLabel#Kicker {{
    color: {TEXT_FAINT};
    font-size: 12.5px;
    font-weight: 700;
    letter-spacing: 1.2px;
}}

QLabel#Mono {{
    font-family: "Cascadia Mono", "JetBrains Mono", "Consolas", monospace;
    font-size: 14.5px;
    color: {TEXT_DIM};
}}

QLabel#MonoVal {{
    font-family: "Cascadia Mono", "JetBrains Mono", "Consolas", monospace;
    font-size: 16px;
    font-weight: 600;
    color: {TEXT};
}}

QLabel#SectionLabel {{
    color: {TEXT_FAINT};
    font-size: 12.5px;
    font-weight: 700;
    letter-spacing: 1.2px;
}}

/* Surface Panels and Cards */
QFrame#Panel {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_SOFT};
    border-radius: 6px;
}}

QFrame#Card {{
    background-color: {SURFACE_CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}

QFrame#HeroCard {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}

QFrame#OfferHeroCard {{
    background-color: #0E1B1E;
    border: 1px solid #144038;
    border-radius: 6px;
}}

QFrame#VerificationRibbon {{
    background-color: #0F131C;
    border-bottom: 1px solid {BORDER_SOFT};
}}

QFrame#Divider {{
    background-color: {BORDER_SOFT};
    border: none;
}}

/* Buttons */
QPushButton {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 6px 12px;
    color: {TEXT};
    font-size: 15px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {SURFACE_3};
    border-color: #384A61;
}}
QPushButton:pressed {{
    background-color: #0E141D;
}}
QPushButton:disabled {{
    color: {TEXT_FAINT};
    background-color: #0B0E14;
    border-color: #171F29;
}}

QPushButton#Primary {{
    background-color: #2563EB;
    border: 1px solid #3B82F6;
    color: #FFFFFF;
    font-weight: 700;
}}
QPushButton#Primary:hover {{
    background-color: #1D4ED8;
    border-color: #60A5FA;
}}

QPushButton#GreenCTA {{
    background-color: #059669;
    border: 1px solid #10B981;
    color: #FFFFFF;
    font-weight: 700;
    border-radius: 5px;
    padding: 6px 14px;
}}
QPushButton#GreenCTA:hover {{
    background-color: #047857;
    border-color: #34D399;
}}

QPushButton#WhatsAppPill {{
    background-color: #0F5132;
    border: 1px solid #198754;
    color: #A3CFBB;
    font-size: 13px;
    font-weight: 700;
    border-radius: 4px;
    padding: 2px 8px;
}}
QPushButton#WhatsAppPill:hover {{
    background-color: #198754;
    color: #FFFFFF;
}}

QPushButton#NavTab {{
    background-color: transparent;
    border: none;
    border-radius: 0px;
    padding: 6px 12px;
    color: {TEXT_DIM};
    font-weight: 600;
    font-size: 15px;
}}
QPushButton#NavTab:hover {{
    color: #FFFFFF;
}}
QPushButton#NavTabActive {{
    background-color: transparent;
    border: none;
    border-bottom: 2px solid {CYAN};
    border-radius: 0px;
    padding: 6px 12px;
    color: #FFFFFF;
    font-weight: 700;
    font-size: 15px;
}}

QPushButton#Ghost {{
    background-color: transparent;
    border: 1px solid {BORDER};
}}
QPushButton#Ghost:hover {{
    background-color: {SURFACE_2};
}}

/* Badges and Tags */
QLabel#BadgeGreen {{
    background-color: rgba(16, 185, 129, 0.16);
    border: 1px solid rgba(16, 185, 129, 0.4);
    color: {GREEN};
    font-size: 12.5px;
    font-weight: 700;
    border-radius: 3px;
    padding: 2px 6px;
    letter-spacing: 0.4px;
}}

QLabel#BadgeAmber {{
    background-color: rgba(245, 158, 11, 0.16);
    border: 1px solid rgba(245, 158, 11, 0.4);
    color: {AMBER};
    font-size: 12.5px;
    font-weight: 700;
    border-radius: 3px;
    padding: 2px 6px;
    letter-spacing: 0.4px;
}}

QLabel#BadgeRed {{
    background-color: rgba(239, 68, 68, 0.18);
    border: 1px solid rgba(239, 68, 68, 0.45);
    color: {RED};
    font-size: 12.5px;
    font-weight: 700;
    border-radius: 3px;
    padding: 2px 6px;
    letter-spacing: 0.4px;
}}

QLabel#BadgeCyan {{
    background-color: rgba(6, 182, 212, 0.16);
    border: 1px solid rgba(6, 182, 212, 0.4);
    color: {CYAN};
    font-size: 12.5px;
    font-weight: 700;
    border-radius: 3px;
    padding: 2px 6px;
    letter-spacing: 0.4px;
}}

QLabel#BadgeDark {{
    background-color: #121822;
    border: 1px solid {BORDER};
    color: {TEXT_DIM};
    font-size: 12.5px;
    font-weight: 600;
    border-radius: 3px;
    padding: 2px 6px;
}}

/* Form inputs */
QLineEdit, QComboBox, QSpinBox {{
    background-color: {BASE};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 7px;
    color: {TEXT};
    font-size: 15px;
    selection-background-color: {ACCENT};
    selection-color: #FFFFFF;
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{
    border-color: #384A61;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border-color: {ACCENT};
}}

QCheckBox {{
    color: {TEXT_DIM};
    spacing: 6px;
    font-size: 15px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 1px solid {BORDER};
    background-color: {BASE};
}}
QCheckBox::indicator:hover {{
    border-color: #384A61;
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

QProgressBar {{
    background-color: #141B26;
    border: none;
    border-radius: 2px;
    height: 4px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {CYAN};
    border-radius: 2px;
}}

QSplitter::handle {{
    background-color: {BORDER_SOFT};
    width: 1px;
}}

QMenu {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 20px 6px 12px;
    border-radius: 4px;
    font-size: 15px;
}}
QMenu::item:selected {{
    background-color: {SURFACE_3};
}}
"""
