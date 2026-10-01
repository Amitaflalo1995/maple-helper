"""The "?" beside game terms: hovering (or clicking) it shows what the term means.

The badge is a small orange circle with a "?" (an image, so it's big enough to notice and to hit).
The explanation is our own popup, always on top: Qt's tooltip opens behind the chat and the tools
window, which stay on top of the game."""
from __future__ import annotations

import html
import tempfile
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import QLabel

from .. import glossary
from . import theme

LANG = "he"          # the UI language; the chat sets it at start
BADGE_PX = 15


def _badge_file() -> str | None:
    """Draw the "?" badge once (needs a running Qt app) and hand its file to the glossary's links."""
    if QGuiApplication.instance() is None:
        return None
    path = Path(tempfile.gettempdir()) / "maplehelper-term-badge.png"
    scale = 3                                   # drawn large, shown at BADGE_PX: crisp on any screen
    size = BADGE_PX * scale
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(theme.ORANGE))
    p.drawEllipse(0, 0, size, size)
    f = QFont("Arial")
    f.setBold(True)
    f.setPixelSize(int(size * 0.72))
    p.setFont(f)
    p.setPen(QColor("white"))
    p.drawText(QRect(0, 0, size, size), Qt.AlignCenter, "?")
    p.end()
    pm.save(str(path), "PNG")
    return path.as_uri()


def setup():
    """Use the image badge in every annotated text from now on."""
    uri = _badge_file()
    if uri:
        glossary.MARK = (f"<img src='{uri}' width='{BADGE_PX}' height='{BADGE_PX}' "
                         f"style='vertical-align: middle'>")


class _Popup(QLabel):
    """One explanation card, on top of everything, beside the mouse."""

    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWordWrap(True)
        self.setTextFormat(Qt.RichText)
        self.setMaximumWidth(320)
        self._hide = QTimer(self, singleShot=True, interval=7000, timeout=self.hide)

    def show_text(self, body: str):
        c = theme.P()
        bg = "#2C2C2E" if theme.MODE == "dark" else "#FFFFFF"
        self.setStyleSheet(f"QLabel {{ background: {bg}; color: {c['text']}; border: 1px solid {theme.ORANGE};"
                           f" border-radius: 10px; padding: 9px 11px; font-size: 13px; }}")
        self.setText(body)
        self.adjustSize()
        at = QCursor.pos() + QPoint(14, 16)
        screen = (QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()).availableGeometry()
        x = at.x() if at.x() + self.width() <= screen.right() else QCursor.pos().x() - self.width() - 14
        y = at.y() if at.y() + self.height() <= screen.bottom() else QCursor.pos().y() - self.height() - 10
        self.move(x, y)
        self.show()
        self.raise_()
        self._hide.start()


_popup: _Popup | None = None


def tip_html(term: str, lang: str) -> str | None:
    text = glossary.explain(term, lang)
    if not text:
        return None
    d = "rtl" if lang != "en" else "ltr"
    return (f"<div dir='{d}'><b style='color:{theme.ORANGE_DEEP};'>{html.escape(term)}</b><br>"
            f"<span style='line-height:135%;'>{html.escape(text)}</span></div>")


def show(link: str, lang: str) -> bool:
    """Show the explanation for a "g:<term>" link; False when the link isn't a term."""
    global _popup
    term = glossary.term_of(link or "")
    if not term:
        return False
    body = tip_html(term, lang)
    if body:
        if _popup is None:
            _popup = _Popup()
        _popup.show_text(body)
    return True


def hide():
    if _popup is not None:
        _popup.hide()


def _hovered(link: str, lang: str):
    if not show(link, lang):
        hide()


def watch(label: QLabel, lang: str) -> QLabel:
    """A rich-text label whose "?" links explain their term on hover and on click."""
    label.setTextFormat(Qt.RichText)
    label.setOpenExternalLinks(False)
    label.setMouseTracking(True)
    label.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
    label.linkHovered.connect(lambda link: _hovered(link, lang))
    label.linkActivated.connect(lambda link: show(link, lang))
    return label


def label(text_html: str, lang: str, obj: str = "RowLabel") -> QLabel:
    lb = QLabel(glossary.annotate(text_html, lang), objectName=obj)
    lb.setWordWrap(True)
    return watch(lb, lang)
