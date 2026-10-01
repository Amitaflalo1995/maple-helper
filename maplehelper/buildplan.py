"""The build plan for the player's job: the AP, SP and equipment tables of the class guide, with the row
for the player's level marked. The tables come from the shipped guides (assets/guides), so they read in
the player's language."""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import guides, plan

KINDS = (("ap", re.compile(r"\bAP allocation", re.I)), ("sp", re.compile(r"\bSP allocation", re.I)),
         ("gear", re.compile(r"Recommended equipment", re.I)))


@dataclass
class PlanTable:
    kind: str                 # ap | sp | gear
    heading: str              # in the player's language
    rows: list[list[str]]     # first row = header
    current: int | None       # index (in rows) of the row for the player's level


def _levels(cell: str) -> tuple[int, int] | None:
    """"10" -> (10, 10), "11-12" / "Levels 30-39" / "Lv 10" -> the range; None when there's no level."""
    m = re.search(r"(\d+)\s*[-–]\s*(\d+)", cell)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"\d+", cell)
    return (int(m.group(0)), int(m.group(0))) if m else None


def current_row(rows: list[list[str]], level: int) -> int | None:
    """The row whose level (range) covers the player's level; else the last row already reached."""
    best = None
    for i, row in enumerate(rows[1:], start=1):
        lv = _levels(row[0]) if row else None
        if not lv:
            continue
        lo, hi = lv
        if lo <= level <= hi:
            return i
        if lo <= level:
            best = i
    return best


def tables(kb, base_class: str, job: str, level: int, lang: str) -> tuple[str | None, list[PlanTable]]:
    """(guide key, the plan tables of the player's class guide) in the player's language."""
    key = plan.class_guide(kb, base_class, job)
    if not key:
        return None, []
    en = guides.book(key, "en")
    local = guides.book(key, lang) or en
    if not en:
        return key, []
    same = len(local.get("blocks", [])) == len(en["blocks"])
    out, heading, heading_local, kinds_seen = [], "", "", set()
    for i, b in enumerate(en["blocks"]):
        if "h2" in b or "h3" in b:
            heading = b.get("h2") or b.get("h3")
            lb = local["blocks"][i] if same else b
            heading_local = lb.get("h2") or lb.get("h3") or heading
            continue
        if "table" not in b:
            continue
        kind = next((k for k, rx in KINDS if rx.search(heading)), None)
        if not kind or (kind, heading) in kinds_seen:
            continue
        kinds_seen.add((kind, heading))
        rows = (local["blocks"][i] if same else b).get("table") or b["table"]
        out.append((PlanTable(kind, heading_local, rows, current_row(b["table"], level)), _levels(heading)))
    # per kind, the table for the player's levels ("levels 10-30"), else the latest one already reached
    picked = []
    for kind, _ in KINDS:
        mine = [(t, r) for t, r in out if t.kind == kind]
        fits = [t for t, r in mine if not r or r[0] <= level <= r[1]]
        if not fits:
            reached = [(r[1], t) for t, r in mine if r and r[0] <= level]
            fits = [max(reached, key=lambda x: x[0])[1]] if reached else [t for t, _ in mine[:1]]
        picked += fits
    return key, picked
