"""The wishlist window: each wished item, who drops it (lowest level first) and where they live."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .. import bidi
from ..i18n import I18n
from ..kb import KnowledgeBase
from .controls import rtl_buttons
from .glass import GlassDialog
from .widgets import EntityCard

SHOWN_DROPPERS = 5


class WishlistDialog(GlassDialog):
    def __init__(self, keys: list[str], kb: KnowledgeBase, lang: str, stylesheet: str):
        self.t = t = I18n(lang or "he")
        super().__init__(t("wishlist"), t.rtl)
        self.setStyleSheet(stylesheet)
        self.resize(500, 640)
        rtl = t.rtl
        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(objectName="Feed")
        self.lay = lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(8)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        keys = [k for k in keys if kb.get(k)]
        if not keys:
            empty = QLabel(bidi.plain(t("wishlist_empty"), rtl), objectName="DialogBody")
            empty.setWordWrap(True)
            lay.addWidget(empty)
        align = (Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignAbsolute
        for k in keys:
            lay.addWidget(EntityCard(kb, k, t.lang))
            droppers = kb.droppers.get(k, [])
            if droppers:
                lines = [t("wish_dropped_by")]
                for m in droppers[:SHOWN_DROPPERS]:
                    e = kb.get(m) or {}
                    lvl = (e.get("props") or {}).get("Level")
                    maps = kb._top_maps(m, n=1)
                    lines.append(f"• {e.get('name', m)}" + (f" (Lv. {lvl})" if lvl else "")
                                 + (f" · {maps[0]}" if maps else ""))
                if len(droppers) > SHOWN_DROPPERS:
                    lines.append(t("pn_more", n=len(droppers) - SHOWN_DROPPERS))
            else:
                lines = [t("wish_no_droppers")]
            for ln in lines:
                lb = QLabel(bidi.plain(ln, rtl), objectName="CardStat")
                lb.setWordWrap(True)
                lb.setAlignment(align)
                lb.setContentsMargins(12, 0, 12, 0)
                lay.addWidget(lb)
            lay.addSpacing(10)
        lay.addStretch(1)

        row = QHBoxLayout()
        row.setContentsMargins(0, 10, 0, 0)
        row.addStretch(1)
        ok = QPushButton(t("close"), objectName="Primary")
        ok.setCursor(Qt.PointingHandCursor)
        ok.setMinimumWidth(160)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        row.addStretch(1)
        outer.addLayout(row)
        rtl_buttons(self, rtl)
