"""The guides library: picks for your character, categories and search, and a clean reader with a
Hebrew/English summary on demand and "Ask about this guide" (tags it in the chat)."""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QStackedWidget, QTextBrowser, QVBoxLayout, QWidget)

from .. import bidi, guides
from ..i18n import I18n
from .controls import rtl_buttons
from .glass import GlassDialog


class GuideRow(QFrame):
    clicked = Signal(str)

    def __init__(self, kb, g: dict, t, rtl: bool):
        super().__init__(objectName="Card")
        self.key = g["key"]
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)
        pic = QLabel()
        pic.setFixedSize(44, 44)
        pic.setAlignment(Qt.AlignCenter)
        img = kb.picture(self.key)
        pm = QPixmap(str(img)) if img else QPixmap()
        if not pm.isNull():
            pic.setPixmap(pm.scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        row.addWidget(pic, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        align = (Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignAbsolute
        title = QLabel(bidi.plain(guides.title(g["key"], g["title"], t.lang), rtl), objectName="CardName")
        title.setWordWrap(True)
        title.setAlignment(align)
        col.addWidget(title)
        meta = t(f"gcat_{g['category']}") + (f" · {t('g_minutes', n=g['minutes'])}" if g.get("minutes") else "")
        sub = QLabel(bidi.plain(meta, rtl), objectName="CardSub")
        sub.setAlignment(align)
        col.addWidget(sub)
        row.addLayout(col, 1)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.key)


class GuidesDialog(GlassDialog):
    ask_requested = Signal(str)          # guide key: tag it in the chat and focus the question box

    def __init__(self, kb, character, lang: str, stylesheet: str, open_key: str | None = None):
        self.t = t = I18n(lang or "he")
        super().__init__(t("guides"), t.rtl)
        self.kb, self.c = kb, character
        self.setStyleSheet(stylesheet)
        self.resize(560, 760)
        self.all = guides.all_guides(kb)
        self.picks = guides.for_you(kb, character)
        self._reading: str | None = None

        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.stack.addWidget(self._library())
        self.stack.addWidget(self._reader())
        rtl_buttons(self, t.rtl)
        if open_key and kb.get(open_key):
            self.open_guide(open_key)

    # library ----------------------------------------------------------------

    def _library(self) -> QWidget:
        t, rtl = self.t, self.t.rtl
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText(bidi.plain(t("g_search"), rtl))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda *_: self._fill())
        lay.addWidget(self.search)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.cats = QButtonGroup(self)
        for cat in guides.CATEGORIES:
            b = QPushButton(bidi.plain(t(f"gcat_{cat}"), rtl), objectName="Chip")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("cat", cat)
            self.cats.addButton(b)
            chips.addWidget(b)
        chips.addStretch(1)
        self.cats.buttons()[0].setChecked(True)
        self.cats.buttonClicked.connect(lambda *_: self._fill())
        lay.addLayout(chips)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(objectName="Feed")
        self.rows = QVBoxLayout(body)
        self.rows.setContentsMargins(0, 0, 6, 0)
        self.rows.setSpacing(8)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)
        self._fill()
        return w

    def _fill(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().hide()   # gone now, not at the next event loop
                item.widget().deleteLater()
        q = self.search.text().strip().lower()
        cat = self.cats.checkedButton().property("cat")
        if q:
            shown = [g for g in self.all if q in g["title"].lower() or q in self.kb.page(g["key"]).lower()
                     or q in guides.text_of(g["key"], self.t.lang).lower()]
        elif cat == "for_you":
            by_key = {g["key"]: g for g in self.all}
            shown = [by_key[k] for k in self.picks if k in by_key]
        else:
            shown = [g for g in self.all if g["category"] == cat]
        for g in shown:
            row = GuideRow(self.kb, g, self.t, self.t.rtl)
            row.clicked.connect(self.open_guide)
            self.rows.addWidget(row)
        if not shown:
            self.rows.addWidget(QLabel(bidi.plain(self.t("g_none"), self.t.rtl), objectName="RowHint"))
        self.rows.addStretch(1)

    # reader -----------------------------------------------------------------

    def _reader(self) -> QWidget:
        t, rtl = self.t, self.t.rtl
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        back = QPushButton(bidi.plain(t("g_back"), rtl), objectName="Link")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        lay.addWidget(back, 0, (Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignAbsolute)   # the reading start
        self.r_title = QLabel(objectName="PageTitle")
        self.r_title.setWordWrap(True)
        self.r_title.setLayoutDirection(Qt.LeftToRight)
        lay.addWidget(self.r_title)
        self.r_meta = QLabel(objectName="CardSub")
        lay.addWidget(self.r_meta)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        ask = QPushButton(bidi.plain(t("g_ask"), rtl), objectName="Primary")
        ask.setCursor(Qt.PointingHandCursor)
        ask.clicked.connect(lambda: (self.ask_requested.emit(self._reading), self.accept()))
        actions.addWidget(ask)
        web = QPushButton(bidi.plain(t("g_web"), rtl), objectName="Link")
        web.setCursor(Qt.PointingHandCursor)
        web.clicked.connect(lambda: webbrowser.open((self.kb.get(self._reading) or {}).get("url", "")))
        actions.addWidget(web)
        actions.addStretch(1)
        lay.addLayout(actions)
        self.stale = QLabel(objectName="RowHint")
        self.stale.setWordWrap(True)
        lay.addWidget(self.stale)
        self.browser = QTextBrowser(objectName="GuideText")
        self.browser.setOpenExternalLinks(True)
        self.browser.setLayoutDirection(Qt.LeftToRight)      # the guides are written in English
        lay.addWidget(self.browser, 1)
        return w

    def open_guide(self, key: str):
        t = self.t
        self._reading = key
        page = self.kb.page(key)
        g, translated, stale = guides.localized(key, page, t.lang)
        rtl = translated and t.rtl
        self.r_title.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        self.r_title.setText(bidi.plain(g.title, rtl))
        meta = t(f"gcat_{guides.category(key)}") + (f" · {t('g_minutes', n=g.minutes)}" if g.minutes else "")
        self.r_meta.setText(bidi.plain(meta, t.rtl))
        self.stale.setVisible(translated and stale)
        self.stale.setText(bidi.plain(t("g_stale"), t.rtl))
        labels = {"pros": t("g_pros") if rtl else "Pros", "cons": t("g_cons") if rtl else "Cons"}
        self.browser.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        # table cells take their direction from the document, not from the cell's dir attribute
        opt = self.browser.document().defaultTextOption()
        opt.setTextDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        self.browser.document().setDefaultTextOption(opt)
        self.browser.setHtml(guides.to_html(g, labels, rtl))
        self.stack.setCurrentIndex(1)
