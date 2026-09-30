"""Colors, fonts and the shared stylesheet."""
from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase

from ..store import ASSETS

ORANGE = "#F08A24"
ORANGE_DARK = "#C9651A"
CREAM = "#FFF6E8"
BROWN = "#4A2A12"
PANEL = "rgba(28, 22, 18, {a})"
BUBBLE_USER = "rgba(240, 138, 36, 0.22)"
BUBBLE_BOT = "rgba(255, 255, 255, 0.07)"
TEXT = "#FFF8EE"
MUTED = "#C9B8A4"
BORDER = "rgba(240, 138, 36, 0.55)"

FONT_FAMILY = "Rubik"


def load_fonts() -> str:
    fam = None
    for f in sorted((ASSETS / "fonts").glob("*.ttf")):
        fid = QFontDatabase.addApplicationFont(str(f))
        if fid >= 0 and not fam:
            fams = QFontDatabase.applicationFontFamilies(fid)
            fam = fams[0] if fams else None
    return fam or "Segoe UI"


def app_font(size: int = 14) -> QFont:
    f = QFont(FONT_FAMILY)
    f.setPixelSize(size)
    return f


def stylesheet(font_family: str, size: int, opacity: float) -> str:
    a = max(0.35, min(1.0, opacity))
    return f"""
    * {{ font-family: "{font_family}"; font-size: {size}px; color: {TEXT}; }}
    #Panel {{ background: {PANEL.format(a=a)}; border: 1px solid {BORDER}; border-radius: 14px; }}
    #TitleBar {{ background: transparent; }}
    #Title {{ font-weight: 600; color: {CREAM}; }}
    #ProfileChip {{ background: rgba(240,138,36,0.18); border: 1px solid {BORDER}; border-radius: 10px;
                    padding: 2px 10px; color: {CREAM}; }}
    #ProfileChip:hover {{ background: rgba(240,138,36,0.32); }}
    QToolButton#IconBtn {{ background: transparent; border: none; padding: 4px; border-radius: 8px; color: {MUTED}; }}
    QToolButton#IconBtn:hover {{ background: rgba(255,255,255,0.10); color: {TEXT}; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 6px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.25); border-radius: 3px; min-height: 24px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    #BubbleUser {{ background: {BUBBLE_USER}; border-radius: 12px; }}
    #BubbleBot {{ background: {BUBBLE_BOT}; border-radius: 12px; }}
    #SystemLine {{ color: {MUTED}; font-size: {size - 2}px; }}
    #Card {{ background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 10px; }}
    #Card:hover {{ border: 1px solid {BORDER}; }}
    #CardName {{ font-weight: 600; color: {CREAM}; }}
    #CardSub {{ color: {MUTED}; font-size: {size - 2}px; }}
    #CardStat {{ color: {TEXT}; font-size: {size - 2}px; }}
    #CardCredit {{ color: {MUTED}; font-size: {size - 4}px; }}
    QLineEdit#Input {{ background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.18);
                       border-radius: 10px; padding: 8px 10px; selection-background-color: {ORANGE}; }}
    QLineEdit#Input:focus {{ border: 1px solid {ORANGE}; }}
    QPushButton#Quick {{ background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.15);
                         border-radius: 12px; padding: 4px 10px; font-size: {size - 2}px; }}
    QPushButton#Quick:hover {{ border: 1px solid {ORANGE}; background: rgba(240,138,36,0.18); }}
    QPushButton#Primary {{ background: {ORANGE}; color: #2A1606; border: none; border-radius: 10px;
                           padding: 8px 16px; font-weight: 600; }}
    QPushButton#Primary:hover {{ background: #FF9C3A; }}
    QPushButton#Primary:disabled {{ background: rgba(240,138,36,0.35); }}
    QPushButton#Secondary {{ background: transparent; border: 1px solid rgba(255,255,255,0.25); border-radius: 10px;
                             padding: 8px 16px; }}
    QPushButton#Secondary:hover {{ border: 1px solid {ORANGE}; }}
    #MicDot {{ background: #E5484D; border-radius: 5px; }}
    QSizeGrip {{ background: transparent; }}
    """
