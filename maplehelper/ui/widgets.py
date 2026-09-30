"""Chat building blocks: message bubbles, entity cards, system lines."""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QTextOption
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from .. import bidi
from ..kb import KnowledgeBase


def _label(text: str = "", name: str | None = None, rich: bool = False, wrap: bool = True) -> QLabel:
    lb = QLabel()
    if name:
        lb.setObjectName(name)
    lb.setTextFormat(Qt.RichText if rich else Qt.PlainText)
    lb.setWordWrap(wrap)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    lb.setText(text)
    return lb


class Bubble(QFrame):
    """A chat message. Direction is decided per paragraph, not by the UI language."""

    def __init__(self, text: str, role: str, ui_rtl: bool):
        super().__init__()
        self.role = role
        self.setObjectName("BubbleUser" if role == "user" else "BubbleBot")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 8, 13, 9)
        self.label = _label(rich=True)
        self.label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        lay.addWidget(self.label)
        self.set_text(text)

    def set_text(self, text: str) -> None:
        self.label.setText(bidi.to_html(text) if text else "")


class BubbleRow(QWidget):
    """iMessage convention: your messages sit on the trailing side (left in Hebrew), answers span the width."""

    def __init__(self, bubble: Bubble, ui_rtl: bool):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        # the layout mirrors in an RTL UI, so "trailing" is the left edge there
        if bubble.role == "user":
            lay.addSpacing(48)
            lay.addStretch(1)
            lay.addWidget(bubble, 0)
        else:
            lay.addWidget(bubble, 1)


class SystemLine(QLabel):
    def __init__(self, text: str):
        super().__init__(bidi.plain(text))
        self.setObjectName("SystemLine")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignHCenter)


# ------------------------------------------------------------------ entity cards

CARD_FIELDS = {
    "monster": [("Level", "level"), ("HP", "HP"), ("EXP", "EXP")],
    "item": [("Level", "level"), ("Attack", "ATT"), ("Defense", "DEF")],
}
FIELD_LABELS_HE = {"level": "לבל", "HP": "HP", "EXP": "EXP", "ATT": "ATT", "DEF": "DEF"}
CATEGORY_LABELS = {
    "monster": ("מפלצת", "Monster"), "item": ("פריט", "Item"), "map": ("מפה", "Map"),
    "npc": ("NPC", "NPC"), "quest": ("קווסט", "Quest"), "skill": ("סקיל", "Skill"),
    "class": ("קלאס", "Class"), "guide": ("מדריך", "Guide"), "shop": ("חנות", "Shop"),
    "crafting": ("Crafting", "Crafting"), "formula": ("נוסחה", "Formula"),
}


class EntityCard(QFrame):
    """Image + official English name + key stats + credit link to NiaMeowDB."""

    clicked = Signal(str)

    def __init__(self, kb: KnowledgeBase, key: str, lang: str):
        super().__init__()
        self.setObjectName("Card")
        self.setCursor(Qt.PointingHandCursor)
        e = kb.get(key) or {}
        self.url = e.get("url")
        he = lang == "he"

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)

        pic = QLabel()
        pic.setFixedSize(56, 56)
        pic.setAlignment(Qt.AlignCenter)
        img = kb.image_path(key)
        if img:
            pm = QPixmap(str(img))
            if not pm.isNull():
                pic.setPixmap(pm.scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        row.addWidget(pic, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(2)
        name = _label(e.get("name", key), "CardName", wrap=True)
        name.setLayoutDirection(Qt.LeftToRight)      # official English name, always LTR
        name.setAlignment(Qt.AlignLeft if not he else Qt.AlignRight)
        col.addWidget(name)

        cat = e.get("category", "")
        sub = CATEGORY_LABELS.get(cat, (cat, cat))[0 if he else 1]
        if e.get("type"):
            sub = f"{sub} · {e['type']}"
        col.addWidget(_label(bidi.plain(sub), "CardSub"))

        stats = self._stats(e, he)
        if stats:
            col.addWidget(_label(bidi.plain(stats), "CardStat"))
        credit = _label("NiaMeowDB (meowdb.com)", "CardCredit")
        col.addWidget(credit)
        row.addLayout(col, 1)

    @staticmethod
    def _stats(e: dict, he: bool) -> str:
        props = e.get("props") or {}
        bits = []
        for k in ("Level", "HP", "EXP", "Required Level", "Attack", "Weapon Attack", "Magic Attack", "Defense"):
            if k in props and props[k] not in (None, "", 0):
                label = {"Level": "לבל", "Required Level": "לבל נדרש"}.get(k, k) if he else k
                bits.append(f"{label}: {props[k]}")
            if len(bits) >= 3:
                break
        return " · ".join(bits)

    def mouseReleaseEvent(self, ev):
        if self.url:
            webbrowser.open(self.url)
        super().mouseReleaseEvent(ev)


class QuickButton(QPushButton):
    def __init__(self, text: str):
        super().__init__(text)
        self.setObjectName("Chip")
        self.setCursor(Qt.PointingHandCursor)
