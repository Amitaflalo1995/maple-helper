"""Patch notes for knowledge-base updates: exactly what changed, so players know what's new."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .. import bidi
from ..i18n import STRINGS, I18n
from .controls import Section, rtl_buttons
from .glass import GlassDialog

SHOWN = 80   # rows per list; the rest is counted


def summary(t: I18n, entries: list[dict]) -> str:
    """'3 new, 12 changed' over one or more updates."""
    total = {"added": 0, "changed": 0, "updated": 0, "removed": 0}
    for e in entries:
        for k in total:
            total[k] += (e.get("counts") or {}).get(k, 0)
    return ", ".join(t(f"pn_n_{k}", n=n) for k, n in total.items() if n)


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


class PatchNotesDialog(GlassDialog):
    def __init__(self, entries: list[dict], lang: str, stylesheet: str):
        self.t = t = I18n(lang or "he")
        super().__init__(t("patch_notes"), t.rtl)
        self.setStyleSheet(stylesheet)
        self.resize(500, 640)
        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(objectName="Feed")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 6, 0)
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

        def section(kind: str, rows: list[dict], row_fn):
            n = counts.get(kind, len(rows))
            if not n:
                return
            sec = Section(t(f"pn_{kind}", n=n), rtl)
            for r in rows[:SHOWN]:
                row_fn(sec, r)
            if n > min(len(rows), SHOWN):
                sec.add_row(t("pn_more", n=n - min(len(rows), SHOWN)))
            lay.addWidget(sec)

        def simple(sec, r):
            sec.add_row(r["name"], hint=_category(t, r.get("category", "")))

        def changed(sec, r):
            # "HP: 45 → 50" reads left to right even in Hebrew (the arrow must point from old to new)
            lines = [f"{bidi.LRE}{f}: {_value(a)} → {_value(b)}{bidi.PDF}" for f, a, b in r.get("props", [])]
            if r.get("drops_added"):
                lines.append(t("pn_drops_added", items=", ".join(r["drops_added"])))
            if r.get("drops_removed"):
                lines.append(t("pn_drops_removed", items=", ".join(r["drops_removed"])))
            if r.get("old_name"):
                lines.append(t("pn_renamed", name=r["old_name"]))
            hint = _category(t, r.get("category", ""))
            sec.add_row(r["name"], hint="\n".join([hint] + lines) if hint else "\n".join(lines))

        section("added", e.get("added", []), simple)
        section("changed", e.get("changed", []), changed)
        section("updated", e.get("updated", []), simple)
        section("removed", e.get("removed", []), simple)
