"""Patch notes for knowledge-base updates: exactly what changed, so players know what's new."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .. import bidi
from ..i18n import STRINGS, I18n
from ..kb import KnowledgeBase
from .controls import Section, rtl_buttons
from .glass import GlassDialog
from .widgets import EntityCard, Selectable

SHOWN = 80   # rows per list; the rest is counted


KINDS = ("added", "changed", "updated", "removed")


def summary(t: I18n, entries: list[dict]) -> str:
    """'3 new, 12 changed' over one or more updates."""
    total = totals(entries)
    return ", ".join(t(f"pn_n_{k}", n=total[k]) for k in KINDS if total[k])


def totals(entries: list[dict]) -> dict[str, int]:
    """How many pages each kind of change touched over these updates, each page once: a page updated in two of
    them is one updated page ("12 pages updated" for 9 pages), one added and then updated is a new page, and
    one added and then removed is nothing. Rows a long update didn't list are counted as it counted them."""
    if len(entries) == 1:
        counts = entries[0].get("counts") or {}
        return {k: counts.get(k, len(entries[0].get(k) or [])) for k in KINDS}
    seen: dict[str, list[str]] = {}            # key -> its kinds, oldest update first
    unlisted = dict.fromkeys(KINDS, 0)
    for e in sorted(entries, key=lambda e: str(e.get("version", ""))):
        counts = e.get("counts") or {}
        for kind in KINDS:
            rows = e.get(kind) or []
            unlisted[kind] += max(0, counts.get(kind, len(rows)) - len(rows))
            for r in rows:
                seen.setdefault(r.get("key") or r.get("name") or id(r), []).append(kind)
    total = dict(unlisted)
    for kinds in seen.values():
        if kinds[0] == "added":
            if kinds[-1] != "removed":
                total["added"] += 1
        elif kinds[-1] == "removed":
            total["removed"] += 1
        else:
            total["changed" if "changed" in kinds else "updated"] += 1
    return total


def _category(t: I18n, cat: str) -> str:
    return t(f"cat_{cat}") if f"cat_{cat}" in STRINGS else cat


def _date(e: dict) -> str:
    """2026-10-02 -> 2.10.2026 (reads the same in both directions)."""
    try:
        y, m, d = (int(x) for x in str(e.get("date") or "").split("-"))
        return f"{d}.{m}.{y}"
    except ValueError:
        return str(e.get("version", ""))


def _value(v) -> str:
    return "—" if v is None or v == "" else str(v)


class ChangeCard(Selectable, QFrame):
    """A chat-style card (picture, name, category) with what changed underneath."""

    def __init__(self, kb: KnowledgeBase, r: dict, sub: str, lines: list[str], rtl: bool):
        super().__init__()
        self.setObjectName("Card")
        if kb.get(r["key"]):
            self._init_selectable(r["key"])      # tap to ask about it, like the cards in the chat
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)
        pic = QLabel()
        pic.setFixedSize(48, 48)
        pic.setAlignment(Qt.AlignCenter)
        img = kb.picture(r["key"])
        pm = QPixmap(str(img)) if img else QPixmap()
        if not pm.isNull():
            pic.setPixmap(pm.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        row.addWidget(pic, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        align = (Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignAbsolute
        for text, name in [(r["name"], "CardName"), (sub, "CardSub")] + [(ln, "CardStat") for ln in lines]:
            lb = QLabel(text if name == "CardName" else bidi.plain(text, rtl), objectName=name)
            lb.setWordWrap(True)
            lb.setAlignment(align)
            col.addWidget(lb)
        row.addLayout(col, 1)

    def mouseReleaseEvent(self, ev):
        if hasattr(self, "key"):
            super().mouseReleaseEvent(ev)


def gutter(rtl: bool) -> tuple[int, int, int, int]:
    """A feed's margins: the room before the scrollbar is on the scrollbar's side, the left in Hebrew (margins
    don't mirror, so the Hebrew cards touched the bar while the gap sat on the empty right side)."""
    return (6, 0, 0, 0) if rtl else (0, 0, 6, 0)


class WhatsNewDialog(GlassDialog):
    """What changed in the app itself, version by version."""

    def __init__(self, notes: list[dict], lang: str, stylesheet: str):
        self.notes = notes            # (opened again as it is after a language or theme switch)
        self.t = t = I18n(lang or "he")
        super().__init__(t("whats_new"), t.rtl)
        self.setStyleSheet(stylesheet)
        self.resize(480, 560)
        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(objectName="Feed")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(*gutter(t.rtl))
        lay.setSpacing(18)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        for n in notes:
            sec = Section(t("version_title", version=n["version"]), t.rtl)
            for line in n.get(t.lang) or n.get("en") or []:
                sec.add_row("•  " + line)
            lay.addWidget(sec)
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
        rtl_buttons(self, t.rtl)


class PatchNotesDialog(GlassDialog):
    def __init__(self, entries: list[dict], lang: str, stylesheet: str, kb: KnowledgeBase):
        self.entries = entries        # (opened again as it is after a language or theme switch)
        self.t = t = I18n(lang or "he")
        super().__init__(t("patch_notes"), t.rtl)
        self.kb = kb
        self.setStyleSheet(stylesheet)
        self.resize(520, 680)
        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(objectName="Feed")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(*gutter(t.rtl))
        lay.setSpacing(18)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        if not entries:
            empty = QLabel(bidi.plain(t("patch_notes_empty"), t.rtl), objectName="DialogBody")
            empty.setWordWrap(True)
            lay.addWidget(empty)
        for e in entries:
            self._entry(lay, e)
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
        rtl_buttons(self, t.rtl)

    def _entry(self, lay: QVBoxLayout, e: dict):
        t, rtl = self.t, self.t.rtl
        title = QLabel(bidi.plain(t("pn_update", date=_date(e)), rtl), objectName="ProfileName")
        lay.addWidget(title)
        counts = e.get("counts") or {}

        def section(kind: str, rows: list[dict], card_fn):
            n = counts.get(kind, len(rows))
            if not n:
                return
            box = QVBoxLayout()
            box.setSpacing(8)
            box.addWidget(QLabel(bidi.plain(t(f"pn_{kind}", n=n), rtl), objectName="SectionHeader"))
            for r in rows[:SHOWN]:
                box.addWidget(card_fn(r))
            if n > min(len(rows), SHOWN):
                more = QLabel(bidi.plain(t("pn_more", n=n - min(len(rows), SHOWN)), rtl), objectName="RowHint")
                more.setAlignment(Qt.AlignHCenter)
                box.addWidget(more)
            lay.addLayout(box)

        def simple(r):
            if self.kb.get(r["key"]):
                return EntityCard(self.kb, r["key"], t.lang)     # exactly the chat's card
            return ChangeCard(self.kb, r, _category(t, r.get("category", "")), [], rtl)

        def changed(r):
            # "HP: 45 → 50" reads left to right even in Hebrew (the arrow must point from old to new)
            lines = [f"{bidi.LRE}{f}: {_value(a)} → {_value(b)}{bidi.PDF}" for f, a, b in r.get("props", [])]
            if r.get("drops_added"):
                lines.append(t("pn_drops_added", items=", ".join(r["drops_added"])))
            if r.get("drops_removed"):
                lines.append(t("pn_drops_removed", items=", ".join(r["drops_removed"])))
            if r.get("old_name"):
                lines.append(t("pn_renamed", name=r["old_name"]))
            return ChangeCard(self.kb, r, _category(t, r.get("category", "")), lines, rtl)

        section("added", e.get("added", []), simple)
        section("changed", e.get("changed", []), changed)
        section("updated", e.get("updated", []), simple)
        section("removed", e.get("removed", []), simple)
