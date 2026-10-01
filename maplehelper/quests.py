"""Quests for the player's level, straight from the KB's quest pages: who gives them, what they ask,
what they pay. Done quests are kept per character (Character.quests_done)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

WINDOW_BELOW = 12     # quests this many levels under you still show (cheap EXP you may have skipped)
WINDOW_ABOVE = 4      # and these coming soon


@dataclass
class Quest:
    key: str
    name: str
    level: int
    npc: str = ""
    area: str = ""
    exp: int = 0
    mesos: int = 0
    job: str = ""                       # "Beginner only", "Warrior" ... ("" = any)
    after: str = ""                     # a quest that must be done first
    needs: list[str] = field(default_factory=list)      # "Green Mushroom Cap x 20", "Defeat Blue Snail x 10"
    rewards: list[str] = field(default_factory=list)    # items (EXP and mesos are separate)


def _section(lines: list[str], head: str, stops=("Pre-requisites", "Requirements", "Rewards", "Description",
                                                  "On Acceptance", "Random reward - one of:")) -> list[str]:
    if head not in lines:
        return []
    out = []
    for ln in lines[lines.index(head) + 1:]:
        if ln in stops:
            break
        if ln:
            out.append(ln)
    return out


_ITEM = re.compile(r"((?:Defeat |Collect )?[A-Z][^x]*?) x ([\d,]+)")


@lru_cache(maxsize=1024)
def _quest(kb, key: str) -> Quest | None:
    e = kb.get(key)
    if not e or e.get("category") != "quest":
        return None
    p = e.get("props") or {}
    lv = p.get("Minimum Level")
    if not isinstance(lv, (int, float)):
        return None
    lines = [ln.strip() for ln in kb.page(key).split("\n---", 2)[-1].splitlines()]
    q = Quest(key, e["name"], int(lv), str(p.get("NPC") or ""), str(p.get("Area") or ""),
              int(p.get("EXP Reward") or 0), int(p.get("Meso Reward") or 0))
    for ln in _section(lines, "Pre-requisites"):
        if ln.startswith("Job "):
            q.job = ln[4:].strip()
        elif ln.startswith("Quest Complete "):
            q.after = ln[len("Quest Complete "):].strip()
    for ln in _section(lines, "Requirements"):
        q.needs += [f"{name.strip()} x {n}" for name, n in _ITEM.findall(ln)] or [ln]
    for ln in _section(lines, "Rewards"):
        if re.fullmatch(r"[\d,]+ EXP( [\d,]+ Mesos)?|[\d,]+ Mesos", ln):
            continue
        q.rewards += [f"{name.strip()} x {n}" for name, n in _ITEM.findall(ln)]
    return q


def quest(kb, key: str) -> Quest | None:
    return _quest(kb, key)


def job_fits(q: Quest, base_class: str, job: str) -> bool:
    if not q.job:
        return True
    j = q.job.lower()
    if "beginner" in j:
        return base_class == "Beginner"
    return base_class.lower() in j or (job or "").lower() in j


def for_level(kb, level: int, base_class: str = "", job: str = "", done: list[str] | None = None) -> dict:
    """{"now": quests you can take (best EXP first), "soon": unlocking in the next levels,
    "town": the citizenship donations (repeatable, 100 items each), "done": count}."""
    done_set = set(done or [])
    now, soon, town = [], [], []
    for k, e in kb.entities.items():
        if e.get("category") != "quest":
            continue
        q = quest(kb, k)
        if not q or (base_class and not job_fits(q, base_class, job)):
            continue
        if k in done_set:
            continue
        if level - WINDOW_BELOW <= q.level <= level:
            (town if q.area == "Citizenship" else now).append(q)
        elif level < q.level <= level + WINDOW_ABOVE:
            soon.append(q)
    now.sort(key=lambda q: (-q.exp, q.level))
    soon.sort(key=lambda q: (q.level, -q.exp))
    town.sort(key=lambda q: -q.exp)
    return {"now": now, "soon": soon, "town": town, "done": len(done_set)}
