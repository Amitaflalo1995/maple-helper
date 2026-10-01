"""The "?" beside game terms: hovering (or clicking) it shows what the term means."""
from __future__ import annotations

import html

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QLabel, QToolTip

from .. import glossary

LANG = "he"          # the UI language; the chat sets it at start


def tip_html(term: str, lang: str) -> str | None:
    text = glossary.explain(term, lang)
    if not text:
        return None
    d = "rtl" if lang != "en" else "ltr"
    return (f"<div dir='{d}' style='max-width: 300px;'><b>{html.escape(term)}</b><br>"
            f"<span style='line-height:130%;'>{html.escape(text)}</span></div>")


def show(link: str, lang: str) -> bool:
    """Show the explanation for a "g:<term>" link; False when the link isn't a term."""
    term = glossary.term_of(link or "")
    if not term:
        return False
    body = tip_html(term, lang)
    if body:
        QToolTip.showText(QCursor.pos() + QPoint(12, 14), body)
    return True


def watch(label: QLabel, lang: str) -> QLabel:
    """A rich-text label whose "?" links explain their term on hover and on click."""
    label.setTextFormat(Qt.RichText)
    label.setOpenExternalLinks(False)
    label.setTextInteractionFlags(label.textInteractionFlags() | Qt.LinksAccessibleByMouse)
    label.linkHovered.connect(lambda link: show(link, lang) or QToolTip.hideText())
    label.linkActivated.connect(lambda link: show(link, lang))
    return label


def label(text_html: str, lang: str, obj: str = "RowLabel") -> QLabel:
    lb = QLabel(glossary.annotate(text_html, lang), objectName=obj)
    lb.setWordWrap(True)
    return watch(lb, lang)
