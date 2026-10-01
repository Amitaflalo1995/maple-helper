"""Pinned answers under the character card, the history search window, and the shareable character card."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QScrollArea,
                               QToolButton, QVBoxLayout, QWidget)

from .. import bidi, pins
from ..i18n import I18n
from .controls import rtl_buttons
from .glass import GlassDialog


def _answer_label(text: str) -> QLabel:
    lb = QLabel(bidi.to_html(text), objectName="PinAnswer")
    lb.setTextFormat(Qt.RichText)
    lb.setWordWrap(True)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lb


class PinsBar(QFrame):
    """'📌 Pinned (2) ▾': tap to open the pinned answers, ✕ on one to unpin it."""

    unpin = Signal(str)

    def __init__(self):
        super().__init__(objectName="Card")
        self.col = QVBoxLayout(self)
        self.col.setContentsMargins(14, 8, 14, 8)
        self.col.setSpacing(6)
        self.head = QPushButton(objectName="PlanLink")
        self.head.setCursor(Qt.PointingHandCursor)
        self.head.clicked.connect(self._toggle)
        self.col.addWidget(self.head)
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body_lay.setSpacing(8)
        self.body.hide()
        self.col.addWidget(self.body)
        self.hide()
        self._items: list[dict] = []
        self._t = I18n("he")

    def show_pins(self, items: list[dict], t, rtl: bool):
        self._items, self._t, self._rtl = items, t, rtl
        self.setVisible(bool(items))
        self.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        self.head.setStyleSheet(f"text-align: {'right' if rtl else 'left'}; font-weight: 600;")
        self._refresh_head()
        while self.body_lay.count():
            w = self.body_lay.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        for p in items:
            box = QFrame(objectName="PinItem")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(2)
            top = QHBoxLayout()
            q = QLabel(bidi.plain(p.get("q") or "", rtl), objectName="CardName")
            q.setWordWrap(True)
            top.addWidget(q, 1)
            x = QToolButton(objectName="Icon", text="✕")
            x.setToolTip(t("unpin"))
            x.setCursor(Qt.PointingHandCursor)
            x.clicked.connect(lambda _=False, a=p["a"]: self.unpin.emit(a))
            top.addWidget(x, 0, Qt.AlignTop)
            bl.addLayout(top)
            bl.addWidget(_answer_label(p["a"]))
            self.body_lay.addWidget(box)

    def _refresh_head(self):
        arrow = "▴" if self.body.isVisible() else "▾"
        self.head.setText(bidi.plain(f"📌 {self._t('pinned', n=len(self._items))} {arrow}", getattr(self, "_rtl", True)))

    def _toggle(self):
        self.body.setVisible(not self.body.isVisible())
        self._refresh_head()


class HistoryDialog(GlassDialog):
    """Search everything asked with this character: 'what did I ask about Mano last week?'"""

    pin_requested = Signal(str, str)

    def __init__(self, pairs: list[dict], name: str, lang: str, stylesheet: str):
        self.t = t = I18n(lang or "he")
        super().__init__(t("history_title", name=name), t.rtl)
        self.pairs = pairs
        self.setStyleSheet(stylesheet)
        self.resize(540, 720)
        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText(bidi.plain(t("history_search"), t.rtl))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda *_: self._fill())
        outer.addWidget(self.search)
        self.count = QLabel(objectName="RowHint")
        outer.addWidget(self.count)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(objectName="Feed")
        self.rows = QVBoxLayout(body)
        self.rows.setContentsMargins(0, 0, 6, 0)
        self.rows.setSpacing(8)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        rtl_buttons(self, t.rtl)
        self._fill()

    def _fill(self):
        t, rtl = self.t, self.t.rtl
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().hide()   # gone now, not at the next event loop
                item.widget().deleteLater()
        q = self.search.text().strip()
        hits = pins.search(self.pairs, q)
        self.count.setText(bidi.plain(t("history_count", n=len(hits)), rtl))
        for p in hits[:80]:
            card = QFrame(objectName="Card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 8, 12, 8)
            cl.setSpacing(3)
            top = QHBoxLayout()
            when = QLabel(time.strftime("%d.%m.%Y %H:%M", time.localtime(p["t"])), objectName="CardSub")
            top.addWidget(when)
            top.addStretch(1)
            pin = QToolButton(objectName="Icon", text="📌")
            pin.setToolTip(t("pin"))
            pin.setCursor(Qt.PointingHandCursor)
            pin.clicked.connect(lambda _=False, p=p, b=pin: (self.pin_requested.emit(p["q"], p["a"]), b.setEnabled(False)))
            top.addWidget(pin)
            cl.addLayout(top)
            qlb = QLabel(bidi.plain(p["q"], rtl), objectName="CardName")
            qlb.setWordWrap(True)
            cl.addWidget(qlb)
            cl.addWidget(_answer_label(p["a"]))
            self.rows.addWidget(card)
        if not hits:
            self.rows.addWidget(QLabel(bidi.plain(t("history_none"), rtl), objectName="RowHint"))
        self.rows.addStretch(1)


def character_card_image(c, avatar, kb, progress: dict | None, t) -> QPixmap:
    """A shareable picture of the character: portrait, name, level and job, EXP bar, map."""
    from ..store import ASSETS
    from .widgets import Avatar, character_image
    w = QFrame(objectName="ShareCard")
    w.setLayoutDirection(Qt.LeftToRight)
    w.setFixedWidth(380)
    lay = QHBoxLayout(w)
    lay.setContentsMargins(18, 16, 18, 14)
    lay.setSpacing(16)
    pic = Avatar(96)
    pic.set_image(character_image(c, avatar, kb))
    lay.addWidget(pic, 0, Qt.AlignTop)
    col = QVBoxLayout()
    col.setSpacing(3)
    name = QLabel(c.name, objectName="ShareName")
    col.addWidget(name)
    col.addWidget(QLabel(f"Lv. {c.level} · {c.job}", objectName="ShareMeta"))
    if progress:
        bar = QProgressBar(objectName="ExpBar")
        bar.setRange(0, 1000)
        bar.setValue(round(progress["pct"] * 10))
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        col.addWidget(bar)
        col.addWidget(QLabel(f"EXP {progress['pct']:g}%", objectName="ExpText"))
    if c.map:
        col.addWidget(QLabel(c.map, objectName="ExpText"))
    col.addStretch(1)
    brand = QHBoxLayout()
    brand.addStretch(1)
    icon = QLabel()
    pm = QPixmap(str(ASSETS / "brand" / "icon-64.png"))
    if not pm.isNull():
        icon.setPixmap(pm.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    brand.addWidget(icon)
    brand.addWidget(QLabel("Maple Helper", objectName="ShareBrand"))
    col.addLayout(brand)
    lay.addLayout(col, 1)
    w.adjustSize()
    w.ensurePolished()
    return w.grab()
