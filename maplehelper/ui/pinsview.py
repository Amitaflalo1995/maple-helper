"""Pinned answers under the character card, the history search window, and the shareable character card."""
from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QScrollArea,
                               QToolButton, QVBoxLayout, QWidget)

from .. import bidi, pins
from ..i18n import I18n
from .controls import rtl_buttons
from .glass import GlassDialog


def short_text(text: str, limit: int) -> str:
    """One line of `text` (whitespace collapsed), cut at a word to about `limit` characters."""
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit].rsplit(" ", 1)[0] if " " in flat[:limit] else flat[:limit]
    return cut.rstrip(" ,.:;-–") + "…"


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
        self.body_lay.setContentsMargins(0, 0, 6, 0)
        self.body_lay.setSpacing(8)
        # long answers scroll inside the bar: open, it takes at most ~40% of the chat, never the whole feed
        self.scroll = _FitScroll(on_width=self.fit)
        self.scroll.setWidget(self.body)
        self.scroll.hide()
        self.col.addWidget(self.scroll)
        self.hide()
        self._items: list[dict] = []
        self._t = I18n("he")

    def show_pins(self, items: list[dict], t, rtl: bool):
        self._items, self._t, self._rtl = items, t, rtl
        self.setVisible(bool(items))
        self.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        # "left" is the leading edge: Qt mirrors style-sheet alignment in a right-to-left UI ("right" put the
        # Hebrew title on the left, seen live)
        self.head.setStyleSheet("text-align: left; font-weight: 600;")
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
            q = QLabel(bidi.ltr_name(pins.shown_question(p.get("q") or ""), rtl), objectName="CardName")
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
        self.fit()

    def _refresh_head(self):
        arrow = "▴" if self.scroll.isVisible() else "▾"
        self.head.setText(bidi.plain(f"📌 {self._t('pinned', n=len(self._items))} {arrow}", getattr(self, "_rtl", True)))

    def _toggle(self):
        self.scroll.setVisible(not self.scroll.isVisible())
        self._refresh_head()
        self.fit()
        QTimer.singleShot(0, self.fit)      # again once the chat has made room for it

    MAX_SHARE = 0.4      # of the room it shares with the conversation
    room = None          # the chat sets it: px that the open list and the conversation share

    def fit(self):
        """As tall as the pinned answers, up to MAX_SHARE of the room; the rest scrolls."""
        if self.scroll.isHidden():
            return
        room = self.room() if self.room else self.window().height()
        cap = max(80, int(room * self.MAX_SHARE))
        w = self.scroll.viewport().width() or self.width()
        lay = self.body.layout()
        want = lay.heightForWidth(w) if lay.hasHeightForWidth() else self.body.sizeHint().height()
        self.scroll.want = min(max(want, 0), cap)
        self.scroll.setMinimumHeight(min(48, self.scroll.want))
        self.scroll.setMaximumHeight(self.scroll.want)
        self.scroll.updateGeometry()



class _FitScroll(QScrollArea):
    """A scroll area that asks for exactly `want` pixels of height (and can shrink when the window is short)."""

    want = 0

    def __init__(self, on_width=None):
        super().__init__()
        self._on_width = on_width
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def sizeHint(self):
        return QSize(super().sizeHint().width(), self.want)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._on_width and e.oldSize().width() != e.size().width():   # wrapped text: new width, new height
            self._on_width()


class HistoryDialog(GlassDialog):
    """Search everything asked with this character: 'what did I ask about Mano last week?'

    Airy by design (live feedback: a wall of full answers was hard to read): one card per question with a
    two-line preview and the pictures of what it was about; tap to read the whole answer, and pick the
    conversation up again in the chat."""

    pin_requested = Signal(str, str)
    continue_requested = Signal(str, str, list)      # question, answer, card keys

    def __init__(self, pairs: list[dict], name: str, lang: str, stylesheet: str, kb=None):
        self.t = t = I18n(lang or "he")
        super().__init__(t("history_title", name=name), t.rtl)
        self.pairs, self.kb = pairs, kb
        self.setStyleSheet(stylesheet)
        self.resize(540, 720)
        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText(bidi.plain(t("history_search"), t.rtl))
        self.search.setClearButtonEnabled(True)
        # rebuilt once typing pauses, not on every key (each pass rebuilds up to PAGE cards)
        self._debounce = QTimer(self, singleShot=True, interval=self.DEBOUNCE_MS, timeout=self._new_search)
        self.search.textChanged.connect(lambda *_: self._debounce.start())
        outer.addWidget(self.search)
        self.initial_focus = self.search
        self._shown = self.PAGE
        self.count = QLabel(objectName="RowHint")
        outer.addWidget(self.count)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(objectName="Feed")
        self.rows = QVBoxLayout(body)
        self.rows.setContentsMargins(0, 0, 6, 0)
        self.rows.setSpacing(10)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        rtl_buttons(self, t.rtl)
        self._fill()

    def _day(self, ts: float) -> str:
        day = time.strftime("%Y-%m-%d", time.localtime(ts))
        if day == time.strftime("%Y-%m-%d"):
            return self.t("day_today")
        if day == time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400)):
            return self.t("day_yesterday")
        return time.strftime("%d.%m.%Y", time.localtime(ts))

    PAGE = 80              # cards built at a time; "Show more" adds the next PAGE
    DEBOUNCE_MS = 150

    def _new_search(self):
        self._shown = self.PAGE
        self._fill()

    def _more(self):
        self._shown += self.PAGE
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
        shown = min(len(hits), self._shown)
        # "80 of 200": the list shows the newest PAGE, the rest behind "Show more"
        count = t("history_count", n=len(hits)) if shown == len(hits) else t("history_count_of", n=shown, total=len(hits))
        self.count.setText(bidi.plain(count, rtl))
        align = (Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignAbsolute
        last_day = None
        for p in hits[:shown]:
            day = self._day(p["t"])
            if day != last_day:
                head = QLabel(bidi.plain(day, rtl), objectName="SectionHeader")
                head.setAlignment(align)
                self.rows.addSpacing(4)
                self.rows.addWidget(head)
                last_day = day
            self.rows.addWidget(self._card(p, align))
        if shown < len(hits):
            more = QPushButton(bidi.plain(t("history_more", n=min(self.PAGE, len(hits) - shown)), rtl),
                               objectName="Secondary")
            more.setCursor(Qt.PointingHandCursor)
            more.setAutoDefault(False)
            more.clicked.connect(self._more)
            self.more_btn = more
            self.rows.addWidget(more, 0, Qt.AlignHCenter)
        if not hits:
            self.rows.addWidget(QLabel(bidi.plain(t("history_none"), rtl), objectName="RowHint"))
        self.rows.addStretch(1)

    def _card(self, p: dict, align) -> QFrame:
        t, rtl = self.t, self.t.rtl
        card = QFrame(objectName="Card")
        card.setCursor(Qt.PointingHandCursor)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(6)
        top = QHBoxLayout()
        # a long question (the inventory check's own text) is cut to a short title until the card opens
        question = pins.shown_question(p["q"])         # not the stored "[about Mano] …"
        short_q = short_text(question, 70)
        # an English question keeps its own order in Hebrew ("?What does Mano drop" read backwards)
        qlb = QLabel(bidi.ltr_name(short_q, rtl), objectName="CardName")
        qlb.setWordWrap(True)
        qlb.setAlignment(align)
        top.addWidget(qlb, 1)
        when = QLabel(time.strftime("%H:%M", time.localtime(p["t"])), objectName="CardSub")
        top.addWidget(when, 0, Qt.AlignTop)
        cl.addLayout(top)
        # two lines of the answer, plain: the whole answer opens on a tap
        # an English answer keeps its "…" at its own end (ltr_name: one block), not on the Hebrew side
        preview = QLabel(bidi.ltr_name(short_text(p["a"].replace("**", ""), 110), rtl), objectName="CardSub")
        preview.setWordWrap(True)
        preview.setAlignment(align)
        cl.addWidget(preview)
        # the pictures under the preview; opened, under the whole answer (above it they split the title from it)
        pics = self._pictures(p.get("entities") or [])
        if pics:
            cl.addWidget(pics)
        full = QWidget()
        fl = QVBoxLayout(full)
        fl.setContentsMargins(0, 6, 0, 0)
        fl.setSpacing(10)
        fl.addWidget(_answer_label(p["a"]))
        actions = QHBoxLayout()
        go = QPushButton(bidi.plain(t("history_continue"), rtl), objectName="Primary")
        go.setCursor(Qt.PointingHandCursor)
        go.setAutoDefault(False)
        go.clicked.connect(lambda _=False, p=p: self.continue_requested.emit(p["q"], p["a"], list(p.get("entities") or [])))
        actions.addWidget(go)
        actions.addStretch(1)
        pin = QPushButton(bidi.plain("📌 " + t("pin"), rtl), objectName="Link")
        pin.setCursor(Qt.PointingHandCursor)
        pin.setAutoDefault(False)
        pin.clicked.connect(lambda _=False, b=pin: (self.pin_requested.emit(question, p["a"]), b.setEnabled(False)))
        actions.addWidget(pin)
        fl.addLayout(actions)
        full.hide()
        cl.addWidget(full)

        def toggle(e, full=full, preview=preview, qlb=qlb, pics=pics):
            if e.button() == Qt.LeftButton:
                opened = not full.isVisible()
                if pics:
                    if opened:
                        fl.insertWidget(1, pics)       # right after the answer
                    else:
                        cl.insertWidget(cl.indexOf(preview) + 1, pics)
                full.setVisible(opened)
                preview.setVisible(not opened)
                qlb.setText(bidi.ltr_name(question if opened else short_q, rtl))
        card.mousePressEvent = toggle
        return card

    def _pictures(self, keys: list[str]) -> QWidget | None:
        """Small pictures of the monsters / items / NPCs the answer was about."""
        kb = self.kb
        if kb is None:
            return None
        row_w = QWidget()
        row = QHBoxLayout(row_w)
        row.setContentsMargins(0, 2, 0, 0)
        row.setSpacing(6)
        shown = 0
        for k in keys:
            e = kb.get(k)
            if not e or k.startswith("map/"):      # a map's picture is a whole minimap: a sliver at 30 px
                continue
            path = kb.picture(k)
            pm = QPixmap(str(path)) if path else QPixmap()
            if pm.isNull():
                continue
            lb = QLabel()
            lb.setFixedSize(30, 30)
            lb.setAlignment(Qt.AlignCenter)
            lb.setPixmap(pm.scaled(30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            lb.setToolTip(e.get("name", k))
            row.addWidget(lb)
            shown += 1
            if shown == 8:
                break
        if not shown:
            return None
        row.addStretch(1)
        return row_w


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
    col.addWidget(QLabel(f"Lv. {c.level} · {c.job_label}", objectName="ShareMeta"))
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
    from .widgets import on_solid_background
    return on_solid_background(w.grab(), 18)
