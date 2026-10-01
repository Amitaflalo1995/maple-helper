"""Liquid-glass look in two neutral appearances: light (white glass, dark text) and
dark (black glass, white text). Maple orange is the only accent.

Tokens follow Apple's system colors (label / secondaryLabel / fills) for each appearance.
"""
from __future__ import annotations

import sys

from PySide6.QtGui import QFont, QFontDatabase

from ..store import ASSETS

ORANGE = "#FF9533"
ORANGE_DEEP = "#F07A12"
CREAM = "#FFF4E6"
RADIUS = 22

PALETTES = {
    "dark": {
        "glass": (28, 28, 30), "glass_alpha": 1.0, "solid_alpha": 1.0,
        "sheen": 14, "rim_top": 60, "rim": 22,
        "text": "#F5F5F7", "muted": "rgba(235,235,245,0.64)", "faint": "rgba(235,235,245,0.40)",
        "fill1": "rgba(255,255,255,0.08)", "fill2": "rgba(255,255,255,0.12)", "fill3": "rgba(255,255,255,0.20)",
        "pressed": "rgba(255,255,255,0.28)", "stroke": "rgba(255,255,255,0.14)", "hair": "rgba(255,255,255,0.07)",
        "scroll": "rgba(255,255,255,0.25)",
    },
    "light": {
        "glass": (242, 242, 247), "glass_alpha": 1.0, "solid_alpha": 1.0,
        "sheen": 0, "rim_top": 40, "rim": 30,
        "text": "#1D1D1F", "muted": "rgba(60,60,67,0.66)", "faint": "rgba(60,60,67,0.42)",
        "fill1": "#FFFFFF", "fill2": "#FFFFFF", "fill3": "#E5E5EA",
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
ICON = {"open": "\ue8a7", "refresh": "\ue72c", "info": "\ue946", "edit": "\ue70f", "delete": "\ue74d", "add": "\ue710", "minimize": "\ue921", "close": "\ue8bb", "settings": "\ue713", "camera": "\ue722", "mic": "\ue720", "send": "\ue74a", "stop": "\ue71a", "copy": "\ue8c8", "star": "\ue734", "star_on": "\ue735", "plan": "\ue8fd", "book": "\ue82d"}
# the same keys without an icon font (a trailing U+FE0E asks for the plain glyph, not the color emoji)
SYMBOL_ICONS = {"open": "\u2197", "refresh": "\u21bb", "info": "\u24d8", "edit": "\u270e", "delete": "\u232b", "add": "+", "minimize": "\u2013",
                "close": "\u2715", "settings": "\u2699\ufe0e", "camera": "\ud83d\udcf7\ufe0e", "mic": "\ud83c\udf99\ufe0e", "send": "\u27a4", "stop": "\u25a0",
                "copy": "\u29c9", "star": "\u2606", "star_on": "\u2605", "plan": "\u2261", "book": "\u2630"}


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
    families = QFontDatabase.families()
    if ICON_FONT not in families:
        ICON_FONT = "Segoe MDL2 Assets"
    if ICON_FONT not in families and sys.platform != "win32":
        # macOS has no Segoe icon fonts: plain Unicode symbols, which the system fonts cover
        ICON_FONT = "Helvetica Neue"
        ICON.update(SYMBOL_ICONS)
    return fam or ("Helvetica Neue" if sys.platform == "darwin" else "Segoe UI")


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
    #SaverBadge {{ font-size: {s - 4}px; font-weight: 600; color: #2E9E5B; background: rgba(52,199,89,0.14);
                   border-radius: 8px; padding: 1px 7px; }}
    QProgressBar#ExpBar {{ background: {c['fill3']}; border: none; border-radius: 3px; }}
    QProgressBar#ExpBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FFA24A, stop:1 {ORANGE_DEEP});
                                  border-radius: 3px; }}
    #ExpText {{ color: {c['muted']}; font-size: {s - 3}px; }}
    #PlanHead {{ color: {c['muted']}; font-size: {s - 2}px; font-weight: 600; padding-top: 6px; }}
    QPushButton#PlanLink {{ background: transparent; border: none; padding: 2px 0; text-align: right; color: {c['text']}; }}
    QPushButton#PlanLink:hover {{ color: {ORANGE}; }}
    #Version {{ font-size: {s - 3}px; font-weight: 300; color: {c['muted']}; background: transparent; }}
    #ProfilePill {{ background: {c['fill2']}; border: 1px solid {c['stroke']}; border-radius: 12px;
                    min-height: 24px; max-height: 24px; padding: 0 11px; font-size: {s - 2}px; font-weight: 500; color: {c['text']}; }}
    #ProfilePill:hover {{ background: {c['fill3']}; }}
    #ProfilePill:pressed {{ background: {c['pressed']}; }}
    QToolButton#Icon {{ font-family: "{ICON_FONT}"; font-size: 14px; color: {c['muted']}; background: transparent;
                        border: none; border-radius: 14px; min-width: 28px; min-height: 28px; }}
    QToolButton#Icon:hover {{ background: {c['fill2']}; color: {c['text']}; }}
    QToolButton#Icon:pressed {{ background: {c['fill3']}; }}
    QToolButton#Icon[active="true"] {{ color: #FF453A; }}
    QToolButton#Icon[wished="true"] {{ color: {ORANGE}; }}
    QToolButton#IconClose {{ font-family: "{ICON_FONT}"; font-size: 11px; color: {c['muted']}; background: transparent;
                             border: none; border-radius: 14px; min-width: 28px; min-height: 28px; }}
    QToolButton#IconClose:hover {{ background: #FF453A; color: #FFFFFF; }}
    QToolButton#IconClose:pressed {{ background: #D70015; color: #FFFFFF; }}

    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 6px; margin: 4px 1px; }}
    QScrollBar::handle:vertical {{ background: {c['scroll']}; border-radius: 3px; min-height: 28px; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}

    #CharacterRow {{ background: transparent; border: none; }}
    #Check {{ color: {ORANGE}; font-size: {s + 2}px; font-weight: 700; }}
    QPushButton#IconDanger {{ font-family: "{ICON_FONT}"; font-size: 13px; color: {c['muted']}; background: transparent;
                              border: none; border-radius: 13px; min-width: 26px; max-width: 26px;
                              min-height: 26px; max-height: 26px; }}
    QPushButton#IconDanger:hover {{ color: #FF3B30; background: {c['fill3']}; }}
    QPushButton#IconPlain {{ font-family: "{ICON_FONT}"; font-size: 13px; color: {c['muted']}; background: transparent;
                             border: none; border-radius: 13px; min-width: 26px; max-width: 26px;
                             min-height: 26px; max-height: 26px; }}
    QPushButton#IconPlain:hover {{ color: {ORANGE}; background: {c['fill3']}; }}
    #Stepper {{ background: {c['fill2']}; border: 1px solid {c['stroke']}; border-radius: 10px; }}
    QToolButton#StepBtn {{ background: transparent; border: none; border-radius: 8px; color: {ORANGE};
                           font-size: {s + 4}px; font-weight: 600; min-width: 30px; min-height: 28px; }}
    QToolButton#StepBtn:hover {{ background: {c['fill3']}; }}
    QToolButton#StepBtn:pressed {{ background: {c['pressed']}; }}
    QToolButton#StepBtn:disabled {{ color: {c['faint']}; }}
    QLineEdit#StepValue {{ background: transparent; border: none; font-weight: 600; padding: 0; color: {c['text']}; }}
    #JobFixed {{ background: {c['fill2']}; border: 1px solid {c['stroke']}; border-radius: 8px; min-height: 28px;
                 max-height: 28px; padding: 0 12px; font-weight: 500; color: {c['text']}; }}
    #InfoNote {{ background: {"rgba(255,149,51,0.12)" if MODE == "dark" else "rgba(255,149,51,0.10)"};
                 border: 1px solid rgba(255,149,51,0.35); border-radius: 12px; }}
    #InfoIcon {{ font-family: "{ICON_FONT}"; font-size: 15px; color: {ORANGE}; }}
    #InfoText {{ color: {c['text']}; font-size: {s - 1}px; }}
    #JobHint {{ color: {c['muted']}; font-size: {s - 3}px; }}
    #ProfileCard {{ background: {c['fill1']}; border: 1px solid {c['hair']}; border-radius: 16px; }}
    #ProfileCard:hover {{ border: 1px solid rgba(255,149,51,0.7); }}
    QToolButton#Refresh {{ font-family: "{ICON_FONT}"; font-size: 15px; color: {c['muted']}; background: transparent;
                           border: none; border-radius: 15px; min-width: 30px; max-width: 30px; min-height: 30px;
                           max-height: 30px; }}
    QToolButton#Refresh:hover {{ background: {c['fill3']}; color: {ORANGE}; }}
    QToolButton#Refresh:disabled {{ color: {ORANGE}; }}
    QToolButton#Refresh:checked {{ color: {ORANGE}; background: {c['fill3']}; }}
    #ProfileName {{ font-size: {s + 1}px; font-weight: 600; color: {c['text']}; }}
    #ProfileMeta {{ font-size: {s - 1}px; font-weight: 500; color: {c['muted']}; }}
    #BubbleUser {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFA24A, stop:1 {ORANGE_DEEP});
                   border-radius: 15px; min-height: 32px; }}
    #BubbleUser QLabel {{ color: #FFFFFF; }}
    #BubbleBot {{ background: {c['fill1']}; border: 1px solid {c['hair']}; border-radius: 15px; min-height: 32px; }}
    #SystemLine {{ color: {c['muted']}; font-size: {s - 2}px; }}

    #Card {{ background: {c['fill1']}; border: 1px solid {c['hair']}; border-radius: 14px; }}
    #Card:hover {{ background: {c['fill2']}; border: 1px solid rgba(255,149,51,0.7); }}
    #GroupHeader {{ background: transparent; border: 1px solid transparent; border-radius: 10px; }}
    #GroupHeader:hover {{ border: 1px solid rgba(255,149,51,0.7); }}
    #TileGridTitle {{ color: {c['muted']}; font-size: {s - 2}px; font-weight: 600; }}
    #BubbleTag {{ color: rgba(255,255,255,0.85); font-size: {s - 3}px; font-weight: 600; }}
    #FocusBar {{ background: rgba(255,149,51,0.12); border: 1px solid rgba(255,149,51,0.55); border-radius: 12px; }}
    QPushButton#TagChip {{ background: {"rgba(255,255,255,0.10)" if MODE == "dark" else "#FFFFFF"};
                           border: 1px solid rgba(255,149,51,0.55); border-radius: 12px; min-height: 24px;
                           max-height: 24px; padding: 0 8px; font-size: {s - 2}px; font-weight: 600; color: {c['text']}; }}
    QPushButton#TagChip:hover {{ background: rgba(255,149,51,0.20); }}
    #FocusText {{ color: {c['text']}; font-size: {s - 1}px; }}
    #TileGrid {{ background: {c['fill1']}; border: 1px solid {c['hair']}; border-radius: 14px; }}
    #Tile {{ background: {"rgba(255,255,255,0.05)" if MODE == "dark" else "#F7F7F9"}; border: 1px solid {c['hair']};
             border-radius: 10px; }}
    #Tile:hover {{ border: 1px solid rgba(255,149,51,0.7); }}
    #Card[selected="true"], #Tile[selected="true"], #GroupHeader[selected="true"] {{
        border: 2px solid {ORANGE}; background: rgba(255,149,51,0.12); }}
    #TileName {{ font-size: {s - 1}px; font-weight: 500; color: {c['text']}; }}
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
    QPushButton#Danger {{ background: #FF3B30; color: #FFFFFF; border: none; border-radius: 12px; min-height: 26px;
                          padding: 4px 18px; font-weight: 600; }}
    QPushButton#Danger:pressed {{ background: #D70015; }}
    QPushButton#Secondary {{ background: {c['fill2']}; border: 1px solid {c['stroke']}; border-radius: 12px; min-height: 26px; padding: 4px 18px; }}
    QPushButton#Secondary:hover {{ background: {c['fill3']}; }}
    QPushButton#Quick {{ background: {c['fill2']}; border: 1px solid {c['stroke']}; border-radius: 14px; min-height: 30px; padding: 4px 12px; }}
    QPushButton#Quick:hover {{ background: {c['fill3']}; }}
    QPushButton#Quick:checked {{ background: rgba(255,149,51,0.12); border: 2px solid {ORANGE}; font-weight: 600; }}
    QLineEdit {{ background: {c['fill2']}; border: 1px solid {c['stroke']}; border-radius: 10px; padding: 7px 10px; }}
    QLineEdit:focus {{ border: 1px solid rgba(255,149,51,0.85); }}

    /* grouped settings (iOS inset-grouped) */
    #SectionHeader {{ color: {c['muted']}; font-size: {s - 2}px; font-weight: 500; padding: 0 14px; }}
    #Group {{ background: {c['fill1']}; border: 1px solid {c['hair']}; border-radius: 14px; }}
    #Separator {{ background: {c['hair']}; border: none; }}
    #RowLabel {{ color: {c['text']}; }}
    #DialogBody {{ font-size: {s + 1}px; color: {c['text']}; line-height: 140%; }}
    #RowHint {{ color: {c['muted']}; font-size: {s - 3}px; }}
    #PageTitle {{ font-size: {s + 8}px; font-weight: 700; letter-spacing: -0.3px; color: {c['text']}; }}
    #PageBody {{ color: {c['muted']}; }}
    #FieldLabel {{ color: {c['muted']}; font-size: {s - 2}px; font-weight: 500; }}
    QPushButton#Link, QPushButton#LinkDanger {{ background: transparent; border: none; min-height: 34px;
                        font-weight: 500; text-align: left; padding: 0; color: {ORANGE}; }}
    QPushButton#LinkDanger {{ color: #FF453A; }}
    QPushButton#Link:pressed, QPushButton#LinkDanger:pressed {{ color: {c['muted']}; }}

    #Segmented {{ background: {"rgba(118,118,128,0.24)" if MODE == "dark" else "#E3E3E8"}; border: none;
                  border-radius: 10px; }}
    QPushButton#Segment {{ background: transparent; border: none; border-radius: 8px; min-height: 26px; max-height: 26px;
                           padding: 0 12px; font-size: {s - 2}px; font-weight: 500; color: {c['text']}; }}
    QPushButton#Segment:checked {{ background: {"#636366" if MODE == "dark" else "#FFFFFF"};
                                   border: 1px solid {"rgba(255,255,255,0.10)" if MODE == "dark" else "rgba(0,0,0,0.10)"};
                                   font-weight: 700; color: {c['text']}; }}
    QPushButton#Segment:!checked {{ color: {c['muted']}; }}
    QPushButton#Segment:hover:!checked {{ background: {c['fill1']}; }}

    QPushButton#Select {{ background: {c['fill2']}; border: 1px solid {c['stroke']}; border-radius: 8px;
                          min-height: 28px; max-height: 28px; padding: 0 28px; color: {c['text']};
                          text-align: left; font-weight: 500; }}
    QPushButton#Select:hover {{ background: {c['fill3']}; }}
    QPushButton#Select:pressed {{ background: {c['pressed']}; }}
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

    QSlider::groove:horizontal {{ height: 6px; background: {"rgba(255,255,255,0.22)" if MODE == "dark" else "rgba(0,0,0,0.13)"};
                                  border-radius: 3px; }}
    QSlider::add-page:horizontal {{ background: {"rgba(255,255,255,0.22)" if MODE == "dark" else "rgba(0,0,0,0.13)"};
                                    border-radius: 3px; }}
    QSlider::sub-page:horizontal {{ background: {ORANGE}; border-radius: 3px; }}
    QSlider::handle:horizontal {{ background: #FFFFFF; width: 24px; height: 24px; margin: -9px 0; border-radius: 12px;
                                  border: 1px solid rgba(0,0,0,0.14); }}

    QListWidget {{ background: transparent; border: none; outline: none; }}
    QListWidget::item {{ padding: 8px 4px; border-radius: 8px; color: {c['text']}; }}
    QListWidget::item:hover {{ background: {c['fill1']}; }}
    QListWidget::item:selected {{ background: rgba(255,149,51,0.22); color: {c['text']}; }}

    QMenu {{ background: {"rgba(44,44,46,0.98)" if MODE == "dark" else "rgba(255,255,255,0.98)"};
             border: 1px solid {c['stroke']}; border-radius: 12px; padding: 5px; }}
    QMenu::item {{ padding: 6px 16px 6px 28px; border-radius: 7px; color: {c['text']}; min-width: 64px; }}
    QMenu::item:selected {{ background: {ORANGE}; color: #FFFFFF; }}
    QMenu::item:disabled {{ color: {c['muted']}; font-weight: 600; font-size: {s - 2}px; }}
    QMenu::indicator {{ width: 14px; height: 14px; left: 8px; }}
    QMenu::separator {{ height: 1px; background: {c['hair']}; margin: 4px 8px; }}
    QToolTip {{ background: {"#2C2C2E" if MODE == "dark" else "#FFFFFF"}; color: {c['text']};
                border: 1px solid {c['stroke']}; border-radius: 6px; padding: 4px 8px; }}
    """


def dialog_background() -> str:
    return "#1C1C1E" if MODE == "dark" else "#F2F2F7"
