"""The guides library: picks for your character, categories and search, and a clean reader with a
Hebrew/English summary on demand and "Ask about this guide" (tags it in the chat)."""
from __future__ import annotations

import threading
import webbrowser

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QStackedWidget, QTextBrowser, QVBoxLayout, QWidget)

from .. import bidi, guides
from ..i18n import I18n
from .controls import rtl_buttons
from .glass import GlassDialog


class _Bridge(QObject):
    summary = Signal(str, str)      # guide key, text ("" = failed)


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

    def __init__(self, kb, character, lang: str, stylesheet: str, summarize=None, open_key: str | None = None):
        """summarize(key, page, lang) -> str | None runs Claude (in a thread); None hides the summary button."""
        self.t = t = I18n(lang or "he")
        super().__init__(t("guides"), t.rtl)
        self.kb, self.c, self.summarize = kb, character, summarize
        self.setStyleSheet(stylesheet)
        self.resize(560, 760)
        self.all = guides.all_guides(kb)
        self.picks = guides.for_you(kb, character)
        self._bridge = _Bridge()
        self._bridge.summary.connect(self._on_summary)
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
        self.sum_btn = QPushButton(bidi.plain(t("g_summary"), rtl), objectName="Primary")
        self.sum_btn.setCursor(Qt.PointingHandCursor)
        self.sum_btn.clicked.connect(self._summarize)
        self.sum_btn.setVisible(self.summarize is not None)
        actions.addWidget(self.sum_btn)
        ask = QPushButton(bidi.plain(t("g_ask"), rtl), objectName="Secondary")
        ask.setCursor(Qt.PointingHandCursor)
        ask.clicked.connect(lambda: (self.ask_requested.emit(self._reading), self.accept()))
        actions.addWidget(ask)
        web = QPushButton(bidi.plain(t("g_web"), rtl), objectName="Link")
        web.setCursor(Qt.PointingHandCursor)
        web.clicked.connect(lambda: webbrowser.open((self.kb.get(self._reading) or {}).get("url", "")))
        actions.addWidget(web)
        actions.addStretch(1)
        lay.addLayout(actions)
        self.lang_btn = QPushButton(objectName="Link")
        self.lang_btn.setCursor(Qt.PointingHandCursor)
        self.lang_btn.clicked.connect(lambda: self.open_guide(self._reading, english=not self._english))
        actions.insertWidget(actions.count() - 1, self.lang_btn)
        self.stale = QLabel(objectName="RowHint")
        self.stale.setWordWrap(True)
        lay.addWidget(self.stale)
        self.sum_box = QLabel(objectName="InfoText")
        self.sum_box.setWordWrap(True)
        self.sum_box.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.sum_frame = QFrame(objectName="InfoNote")
        sl = QVBoxLayout(self.sum_frame)
        sl.setContentsMargins(12, 10, 12, 10)
        sl.addWidget(self.sum_box)
        self.sum_frame.hide()
        lay.addWidget(self.sum_frame)
        self.browser = QTextBrowser(objectName="GuideText")
        self.browser.setOpenExternalLinks(True)
        self.browser.setLayoutDirection(Qt.LeftToRight)      # the guides are written in English
        lay.addWidget(self.browser, 1)
        return w

    def open_guide(self, key: str, english: bool = False):
        t = self.t
        self._reading = key
        page = self.kb.page(key)
        g, translated, stale = guides.localized(key, page, "en" if english else t.lang)
        self._english = not translated
        rtl = translated and t.rtl
        self.r_title.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        self.r_title.setText(bidi.plain(g.title, rtl))
        meta = t(f"gcat_{guides.category(key)}") + (f" · {t('g_minutes', n=g.minutes)}" if g.minutes else "")
        self.r_meta.setText(bidi.plain(meta, t.rtl))
        has_translation = guides.translation(key, t.lang) is not None
        self.lang_btn.setVisible(has_translation)
        self.lang_btn.setText(bidi.plain(t("g_read_he" if self._english else "g_read_en"), t.rtl))
        self.stale.setVisible(translated and stale)
        self.stale.setText(bidi.plain(t("g_stale"), t.rtl))
        labels = {"pros": t("g_pros") if rtl else "Pros", "cons": t("g_cons") if rtl else "Cons"}
        self.browser.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        # table cells take their direction from the document, not from the cell's dir attribute
        opt = self.browser.document().defaultTextOption()
        opt.setTextDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        self.browser.document().setDefaultTextOption(opt)
        self.browser.setHtml(guides.to_html(g, labels, rtl))
        self.sum_frame.hide()
        self.sum_btn.setEnabled(True)
        cached = guides.summary_path(key, t.lang, self.kb.page(key))
        if cached.exists():
            self._show_summary(cached.read_text(encoding="utf-8"))
        self.stack.setCurrentIndex(1)

    def _summarize(self):
        key, lang = self._reading, self.t.lang
        page = self.kb.page(key)
        self.sum_btn.setEnabled(False)
        self._show_summary(self.t("g_summarizing"))

        def work():
            text = self.summarize(key, page, lang) or ""
            if text:
                path = guides.summary_path(key, lang, page)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            self._bridge.summary.emit(key, text)
        threading.Thread(target=work, daemon=True).start()

    def _on_summary(self, key: str, text: str):
        if key != self._reading:
            return
        self.sum_btn.setEnabled(True)
        self._show_summary(text or self.t("err_generic"))

    def _show_summary(self, text: str):
        self.sum_box.setText(bidi.to_html(text))
        self.sum_frame.show()
