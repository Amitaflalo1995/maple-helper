"""Crafting professions from the KB's crafting pages (Smithing, Weaponcrafting, Tailoring, Woodcrafting,
Leatherworking, Arcforge): every recipe by profession level, with its ingredients, EXP and cost."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

PROFESSIONS = ("smithing", "weaponcrafting", "tailoring", "woodcrafting", "leatherworking", "arcforge")
NAMES = {p: p.capitalize() for p in PROFESSIONS}


@dataclass
class Recipe:
    name: str
    level: int                      # profession level that unlocks it
    exp: int
    catalyst: int                   # mesos paid to craft
    net: int                        # mesos gained (+) or burned (-) counting ingredients at NPC value
    exp_per_meso: float
    mats: str                       # "Farm only", "Mixed", ...
    ingredients: list[tuple[int, str]] = field(default_factory=list)   # (count, name)


@dataclass
class Level:
    level: int
    needs_exp: int | None           # profession EXP to reach this level
    char_level: int | None          # character level it asks for
    recipes: list[Recipe] = field(default_factory=list)


def _int(text: str) -> int:
    m = re.search(r"[-+]?\s*[\d,]+", text or "")
    return int(m.group(0).replace(",", "").replace(" ", "")) if m else 0


def _float(text: str) -> float:
    m = re.search(r"\d+(\.\d+)?", text or "")
    return float(m.group(0)) if m else 0.0


@lru_cache(maxsize=8)
def _levels(page: str) -> tuple[Level, ...]:
    lines = [ln.strip() for ln in page.split("\n---", 2)[-1].splitlines()]
    out: list[Level] = []
    cur: Level | None = None
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = re.fullmatch(r"Lv\. (\d+)", ln)
        if m:
            cur = next((lv for lv in out if lv.level == int(m.group(1))), None)
            if cur is None:
                cur = Level(int(m.group(1)), None, None)
                out.append(cur)
            need = re.match(r"needs ([\d,]+) EXP · char Lv\. (\d+)", lines[i + 1] if i + 1 < len(lines) else "")
            if need:
                cur.needs_exp, cur.char_level = _int(need.group(1)), int(need.group(2))
            i += 1
            continue
        row = re.fullmatch(r"(\d+) \| (.+)", ln)
        if cur and row and i + 2 < len(lines) and lines[i + 2].startswith("|"):
            ing = [(int(n), name.strip()) for n, name in re.findall(r"(\d+) x (.+?)(?=\s+\d+ x |$)", lines[i + 1])]
            vals = [v.strip() for v in lines[i + 2].strip("| ").split("|")]
            if len(vals) >= 7 and not any(r.name == row.group(2).strip() for r in cur.recipes):
                cur.recipes.append(Recipe(row.group(2).strip(), cur.level, _int(vals[0]), _int(vals[1]), _int(vals[5]),
                                          _float(vals[6]), vals[7] if len(vals) > 7 else "", ing))
            i += 3
            continue
        i += 1
    return tuple(out)


def levels(kb, profession: str) -> tuple[Level, ...]:
    return _levels(kb.page(f"crafting/efficiency__{profession}"))


def max_level(kb, profession: str) -> int:
    return max((lv.level for lv in levels(kb, profession)), default=1)


def for_level(kb, profession: str, level: int) -> tuple[Level | None, Level | None]:
    """(the recipes at your profession level, the ones the next level opens), best EXP per meso first."""
    lv = {x.level: x for x in levels(kb, profession)}
    now, nxt = lv.get(level), lv.get(level + 1)
    for x in (now, nxt):
        if x:
            x.recipes.sort(key=lambda r: (-r.exp_per_meso, -r.exp))
    return now, nxt
