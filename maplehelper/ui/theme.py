"""Liquid-glass look in two neutral appearances: light (white glass, dark text) and
dark (black glass, white text). Maple orange is the only accent.

Tokens follow Apple's system colors (label / secondaryLabel / fills) for each appearance.
"""
from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase

from ..store import ASSETS

ORANGE = "#FF9533"
ORANGE_DEEP = "#F07A12"
CREAM = "#FFF4E6"
RADIUS = 22

PALETTES = {
    "dark": {
        "glass": (18, 18, 20), "glass_alpha": 0.58, "solid_alpha": 0.95,
        "sheen": 30, "rim_top": 95, "rim": 26,
        "text": "#F5F5F7", "muted": "rgba(235,235,245,0.64)", "faint": "rgba(235,235,245,0.40)",
        "fill1": "rgba(255,255,255,0.08)", "fill2": "rgba(255,255,255,0.12)", "fill3": "rgba(255,255,255,0.20)",
        "pressed": "rgba(255,255,255,0.28)", "stroke": "rgba(255,255,255,0.14)", "hair": "rgba(255,255,255,0.07)",
        "scroll": "rgba(255,255,255,0.25)",
    },
    "light": {
        "glass": (250, 250, 252), "glass_alpha": 0.66, "solid_alpha": 0.97,
        "sheen": 70, "rim_top": 230, "rim": 90,
        "text": "#1D1D1F", "muted": "rgba(60,60,67,0.66)", "faint": "rgba(60,60,67,0.42)",
        "fill1": "rgba(255,255,255,0.55)", "fill2": "rgba(255,255,255,0.72)", "fill3": "rgba(255,255,255,0.92)",
        "pressed": "rgba(230,230,235,0.95)", "stroke": "rgba(0,0,0,0.08)", "hair": "rgba(0,0,0,0.05)",
        "scroll": "rgba(0,0,0,0.25)",
    },
}
MODE = "dark"


def P() -> dict:
    return PALETTES.get(MODE, PALETTES["dark"])


# legacy names still used by toasts/dialogs (resolved at call time through P())
TEXT = "#F5F5F7"
MUTED = "rgba(235,235,245,0.64)"
BORDER = "rgba(255,149,51,0.55)"

FONT_FAMILY = "Rubik"
ICON_FONT = "Segoe Fluent Icons"
ICON = {"minimize": "", "close": "", "settings": "", "camera": "", "mic": "", "send": "", "stop": ""}


def set_mode(mode: str) -> None:
    global MODE, TEXT, MUTED
    MODE = mode if mode in PALETTES else "dark"
    TEXT, MUTED = P()["text"], P()["muted"]


def load_fonts() -> str:
    fam = None
    for f in sorted((ASSETS / "fonts").glob("*.ttf")):
        fid = QFontDatabase.addApplicationFont(str(f))
        if fid >= 0 and not fam:
            fams = QFontDatabase.applicationFontFamilies(fid)
            fam = fams[0] if fams else None
    global ICON_FONT
    if ICON_FONT not in QFontDatabase.families():
        ICON_FONT = "Segoe MDL2 Assets"
    return fam or "Segoe UI"


def app_font(size: int = 14) -> QFont:
    f = QFont(FONT_FAMILY)
    f.setPixelSize(size)
    return f


def stylesheet(font_family: str, size: int, opacity: float = 1.0) -> str:
    s, c = size, P()
    return f"""
    * {{ font-family: "{font_family}"; font-size: {s}px; color: {c['text']}; }}
    QWidget#Overlay, QWidget#Feed {{ background: transparent; }}
    #Title {{ font-size: {s + 1}px; font-weight: 600; letter-spacing: -0.2px; color: {c['text']}; }}
    #ProfilePill {{ background: {c['fill2']}; border: 1px solid {c['stroke']}; border-radius: 12px;
                    min-height: 24px; max-height: 24px; padding: 0 11px; font-size: {s - 2}px; font-weight: 500; color: {c['text']}; }}
    #ProfilePill:hover {{ background: {c['fill3']}; }}
    #ProfilePill:pressed {{ background: {c['pressed']}; }}
    QToolButton#Icon {{ font-family: "{ICON_FONT}"; font-size: 14px; color: {c['muted']}; background: transparent;
                        border: none; border-radius: 14px; min-width: 28px; min-height: 28px; }}
    QToolButton#Icon:hover {{ background: {c['fill2']}; color: {c['text']}; }}
    QToolButton#Icon:pressed {{ background: {c['fill3']}; }}
    QToolButton#Icon[active="true"] {{ color: #FF453A; }}
    QToolButton#IconClose {{ font-family: "{ICON_FONT}"; font-size: 11px; color: {c['muted']}; background: transparent;
                             border: none; border-radius: 14px; min-width: 28px; min-height: 28px; }}
    QToolButton#IconClose:hover {{ background: #FF453A; color: #FFFFFF; }}
    QToolButton#IconClose:pressed {{ background: #D70015; color: #FFFFFF; }}

    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 6px; margin: 4px 1px; }}
    QScrollBar::handle:vertical {{ background: {c['scroll']}; border-radius: 3px; min-height: 28px; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}

    #BubbleUser {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFA24A, stop:1 {ORANGE_DEEP});
                   border-radius: 18px; }}
    #BubbleUser QLabel {{ color: #FFFFFF; }}
    #BubbleBot {{ background: {c['fill1']}; border: 1px solid {c['hair']}; border-radius: 18px; }}
    #SystemLine {{ color: {c['muted']}; font-size: {s - 2}px; }}

    #Card {{ background: {c['fill1']}; border: 1px solid {c['hair']}; border-radius: 14px; }}
    #Card:hover {{ background: {c['fill2']}; }}
    #CardName {{ font-weight: 600; color: {c['text']}; }}
    #CardSub {{ color: {c['muted']}; font-size: {s - 2}px; }}
    #CardStat {{ color: {c['text']}; font-size: {s - 2}px; }}
    #CardCredit {{ color: {c['faint']}; font-size: {s - 4}px; }}

    QPushButton#Chip {{ background: {c['fill2']}; border: 1px solid {c['stroke']}; border-radius: 14px;
                        min-height: 28px; max-height: 28px; padding: 0 13px; font-size: {s - 2}px; font-weight: 500; color: {c['text']}; }}
    QPushButton#Chip:hover {{ background: {c['fill3']}; }}
    QPushButton#Chip:pressed {{ background: {c['pressed']}; }}

    #Capsule {{ background: {c['fill2']}; border: 1px solid {c['stroke']}; border-radius: 21px; }}
    #Capsule[focus="true"] {{ border: 1px solid rgba(255,149,51,0.85); }}
    QLineEdit#Input {{ background: transparent; border: none; padding: 0 4px; selection-background-color: {ORANGE};
                       color: {c['text']}; }}
    QToolButton#Send {{ font-family: "{ICON_FONT}"; font-size: 13px; color: #FFFFFF; border: none; border-radius: 15px;
                        min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px;
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFA24A, stop:1 {ORANGE_DEEP}); }}
    QToolButton#Send:pressed {{ background: {ORANGE_DEEP}; }}
    QToolButton#Send:disabled {{ background: {c['fill2']}; color: {c['faint']}; }}

    QPushButton#Primary {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFA24A, stop:1 {ORANGE_DEEP});
                           color: #FFFFFF; border: none; border-radius: 12px; min-height: 26px; padding: 4px 18px; font-weight: 600; }}
    QPushButton#Primary:pressed {{ background: {ORANGE_DEEP}; }}
    QPushButton#Primary:disabled {{ background: {c['fill2']}; color: {c['faint']}; }}
    QPushButton#Secondary {{ background: {c['fill2']}; border: 1px solid {c['stroke']}; border-radius: 12px; min-height: 26px; padding: 4px 18px; }}
    QPushButton#Secondary:hover {{ background: {c['fill3']}; }}
    QPushButton#Quick {{ background: {c['fill2']}; border: 1px solid {c['stroke']}; border-radius: 14px; min-height: 30px; padding: 4px 12px; }}
    QPushButton#Quick:checked {{ background: rgba(255,149,51,0.28); border: 1px solid rgba(255,149,51,0.8); }}
    QPushButton#Quick:hover {{ background: {c['fill3']}; }}
    QLineEdit {{ background: {c['fill2']}; border: 1px solid {c['stroke']}; border-radius: 10px; padding: 7px 10px; }}
    QLineEdit:focus {{ border: 1px solid rgba(255,149,51,0.85); }}

    /* grouped settings (iOS inset-grouped) */
    #SectionHeader {{ color: {c['muted']}; font-size: {s - 2}px; font-weight: 500; padding: 0 14px; }}
    #Group {{ background: {c['fill1']}; border: 1px solid {c['hair']}; border-radius: 14px; }}
    #Separator {{ background: {c['hair']}; border: none; }}
    #RowLabel {{ color: {c['text']}; }}
    #RowHint {{ color: {c['muted']}; font-size: {s - 3}px; }}
    QPushButton#Link, QPushButton#LinkDanger {{ background: transparent; border: none; min-height: 34px;
                        font-weight: 500; text-align: right; padding: 0; color: {ORANGE}; }}
    QPushButton#LinkDanger {{ color: #FF453A; }}
    QPushButton#Link:pressed, QPushButton#LinkDanger:pressed {{ color: {c['muted']}; }}

    #Segmented {{ background: {c['fill2']}; border: 1px solid {c['hair']}; border-radius: 10px; }}
    QPushButton#Segment {{ background: transparent; border: none; border-radius: 8px; min-height: 26px; max-height: 26px;
                           padding: 0 12px; font-size: {s - 2}px; font-weight: 500; color: {c['text']}; }}
    QPushButton#Segment:checked {{ background: {"rgba(255,255,255,0.22)" if MODE == "dark" else "#FFFFFF"};
                                   border: 1px solid {c['stroke']}; }}
    QPushButton#Segment:hover:!checked {{ background: {c['fill1']}; }}

    QComboBox {{ background: {c['fill2']}; border: 1px solid {c['stroke']}; border-radius: 10px; min-height: 26px;
                 padding: 0 10px; color: {c['text']}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox::down-arrow {{ image: none; width: 0; height: 0; }}
    QComboBox QAbstractItemView {{ background: {"#2C2C2E" if MODE == "dark" else "#FFFFFF"}; color: {c['text']};
                                   border: 1px solid {c['stroke']}; border-radius: 10px; padding: 4px; outline: none;
                                   selection-background-color: {ORANGE}; selection-color: #FFFFFF; }}
    QSpinBox {{ background: {c['fill2']}; border: 1px solid {c['stroke']}; border-radius: 10px; min-height: 26px;
                padding: 0 8px; color: {c['text']}; }}
    QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; border: none; background: transparent; }}

    QSlider::groove:horizontal {{ height: 4px; background: {c['fill3']}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {ORANGE}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: #FFFFFF; width: 22px; height: 22px; margin: -9px 0; border-radius: 11px;
                                  border: 1px solid rgba(0,0,0,0.12); }}

    QListWidget {{ background: transparent; border: none; outline: none; }}
    QListWidget::item {{ padding: 8px 4px; border-radius: 8px; color: {c['text']}; }}
    QListWidget::item:hover {{ background: {c['fill1']}; }}
    QListWidget::item:selected {{ background: rgba(255,149,51,0.22); color: {c['text']}; }}

    QMenu {{ background: {"#2C2C2E" if MODE == "dark" else "#FFFFFF"}; border: 1px solid {c['stroke']};
             border-radius: 12px; padding: 6px; }}
    QMenu::item {{ padding: 7px 18px; border-radius: 7px; color: {c['text']}; }}
    QMenu::item:selected {{ background: {ORANGE}; color: #FFFFFF; }}
    QToolTip {{ background: {"#2C2C2E" if MODE == "dark" else "#FFFFFF"}; color: {c['text']};
                border: 1px solid {c['stroke']}; border-radius: 6px; padding: 4px 8px; }}
    """


def dialog_background() -> str:
    return "#1C1C1E" if MODE == "dark" else "#F2F2F7"
