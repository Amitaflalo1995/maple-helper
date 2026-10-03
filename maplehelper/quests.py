"""Quests for the player's level, straight from the KB's quest pages: who gives them, what they ask,
what they pay. Done quests are kept per character (Character.quests_done)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from . import availability

WINDOW_BELOW = 12     # quests this many levels under you still show (cheap EXP you may have skipped)
WINDOW_ABOVE = 4      # and these coming soon


@dataclass
class Quest:
    key: str
    name: str
    level: int                          # to take it ("Minimum Level"; a page without one: level 1)
    npc: str = ""
    area: str = ""
    exp: int = 0
    mesos: int = 0
    job: str = ""                       # "Beginner only", "Warrior" ... ("" = any)
    afters: list[str] = field(default_factory=list)     # every quest that must be done first ("Quest Complete")
    needs: list[str] = field(default_factory=list)      # "Green Mushroom Cap x 20", "Defeat Blue Snail x 10"
    rewards: list[str] = field(default_factory=list)    # items you surely get (EXP, mesos and fame are separate)
    fame: int = 0
    # "Pick one (class-specific)": the choices per class ("Warrior" -> [...], "Any Class" -> [...]); you pick one
    class_rewards: dict[str, list[str]] = field(default_factory=dict)
    # "Random reward - one of:": the set per class, each with its odds ("Bronze Ore x 7 (16.7%)"); you get one
    random_rewards: dict[str, list[str]] = field(default_factory=dict)
    complete_level: int = 0             # "Level 52+ to complete": taken earlier, finished only from this level
    grade: tuple[str, int] | None = None                # ("Henesys", 9): the citizenship grade it asks
    profession: tuple[str, int] | None = None           # ("Smithing", 5): "Profession Smithing Lv. 5+"

    def matches(self, query: str) -> bool:
        """The quest search: every word of the query in its name, NPC, area, what it asks or what it gives."""
        text = " ".join([self.name, self.npc, self.area, *self.needs, *self.rewards,
                         *(r for rs in self.class_rewards.values() for r in rs)]).lower()
        return all(w in text for w in query.lower().split())

    @property
    def after(self) -> str:
        """The quests to do first, as one line ("A, B")."""
        return ", ".join(self.afters)

    def _for_class(self, table: dict[str, list[str]], base_class: str) -> list[str]:
        own = table.get(base_class, []) if base_class else []
        return own + [x for x in table.get("Any Class", []) if x not in own]

    def rewards_pick(self, base_class: str) -> list[str]:
        """The class-specific reward choices for this class, and the ones for any class (pick one)."""
        return self._for_class(self.class_rewards, base_class)

    def rewards_random(self, base_class: str) -> list[str]:
        """The random reward set for this class, and the one for any class (you get one of them)."""
        return self._for_class(self.random_rewards, base_class)

    def opens_at(self) -> int:
        """The level it can be done at: to take it, and to complete it."""
        return max(self.level, self.complete_level)


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


# "Defeat Dark Axe Stump x 100 Dexterity Potion x 5": each name runs up to its own " x <count>"
# (a lowercase x inside a name, "Axe" or "Dexterity", is part of the name)
_ITEM = re.compile(r"((?:Defeat |Collect )?\S.*?) x ([\d,]+)(?!\S)")
# a random reward with its odds: "Bronze Ore x 7 16.7 %"
_ODDS_ITEM = re.compile(r"(\S.*?) x ([\d,]+) ([\d.]+) %")
# the class headers inside a reward block ("Any Class" and "Beginner" too)
CLASSES = ("Warrior", "Magician", "Bowman", "Thief", "Pirate", "Beginner", "Any Class")
_GRADE = re.compile(r"^(.+?): Citizenship grade (\d+)\s*")
_COMPLETE_LV = re.compile(r"Level (\d+)\+ to complete")
_PROFESSION = re.compile(r"^Profession (\w+) Lv\. (\d+)\+")


def _rewards_by_class(lines: list[str], head: str, parse) -> dict[str, list[str]]:
    """A "Pick one (class-specific):" / "Random reward - one of:" block: class header lines, then their items."""
    out: dict[str, list[str]] = {}
    if head not in lines:
        return out
    cls = "Any Class"
    for ln in lines[lines.index(head) + 1:]:
        if ln in CLASSES:
            cls = ln
            continue
        items = parse(ln)
        if not items:
            break                    # the next section ("Description", "On Acceptance", ...)
        out.setdefault(cls, []).extend(items)
    return out


@lru_cache(maxsize=1024)
def _quest(kb, key: str) -> Quest | None:
    e = kb.get(key)
    if not e or e.get("category") != "quest":
        return None
    p = e.get("props") or {}
    lv = p.get("Minimum Level")
    if not isinstance(lv, (int, float)):
        lv = 1                       # no level line ("Bringing a Mirror to Heena"): anyone can take it
    lines = [ln.strip() for ln in kb.page(key).split("\n---", 2)[-1].splitlines()]
    q = Quest(key, e["name"], int(lv), str(p.get("NPC") or ""), str(p.get("Area") or ""),
              int(p.get("EXP Reward") or 0), int(p.get("Meso Reward") or 0))
    for ln in _section(lines, "Pre-requisites"):
        # "Henesys: Citizenship grade 5 Level 32+ to complete Quest Complete First Greeting with Chief Stan"
        g = _GRADE.match(ln)
        if g:
            q.grade = (g.group(1), int(g.group(2)))
            ln = ln[g.end():]
        c = _COMPLETE_LV.search(ln)
        if c:
            q.complete_level = int(c.group(1))
            ln = ln[c.end():].strip()
        pr = _PROFESSION.match(ln)
        if ln.startswith("Job "):
            q.job = ln[4:].strip()
        elif ln.startswith("Quest Complete "):
            q.afters.append(ln[len("Quest Complete "):].strip())
        elif pr:
            q.profession = (pr.group(1), int(pr.group(2)))
    for ln in _section(lines, "Requirements"):
        q.needs += [f"{name.strip()} x {n}" for name, n in _ITEM.findall(ln)] or [ln]
    pick = False                     # inside "Pick one (class-specific):"
    for ln in _section(lines, "Rewards"):
        fame = re.search(r"\+ ?(\d+) Fame", ln)
        if fame:
            q.fame = int(fame.group(1))
        if re.fullmatch(r"([\d,]+ EXP)?\s*([\d,]+ Mesos)?\s*(\+ ?\d+ Fame)?", ln):
            continue
        if ln.startswith("Pick one (class-specific)"):
            pick = True
            break
        q.rewards += [f"{name.strip()} x {n}" for name, n in _ITEM.findall(ln)]
    if pick:
        q.class_rewards = _rewards_by_class(
            lines, next(ln for ln in lines if ln.startswith("Pick one (class-specific)")),
            lambda ln: [f"{name.strip()} x {n}" for name, n in _ITEM.findall(ln)])
    q.random_rewards = _rewards_by_class(
        lines, "Random reward - one of:",
        lambda ln: [f"{name.strip()} x {n} ({pct}%)" for name, n, pct in _ODDS_ITEM.findall(ln)])
    return q


def quest(kb, key: str) -> Quest | None:
    return _quest(kb, key)


def job_fits(q: Quest, base_class: str, job: str) -> bool:
    if not q.job:
        return True
    j = q.job.lower()
    if "beginner" in j:
        # a character still a Beginner, whatever class they plan (the profile's class can be set ahead)
        return base_class == "Beginner" or (job or "") == "Beginner"
    return base_class.lower() in j or (job or "").lower() in j


def craft_fits(q: Quest, crafts: dict | None) -> bool:
    """A "Profession X Lv. N+" quest: the character's level in that profession reaches N (Character.crafts)."""
    if not q.profession or crafts is None:
        return True
    name, lv = q.profession
    return int(crafts.get(name.lower(), 0) or 0) >= lv


def for_level(kb, level: int, base_class: str = "", job: str = "", done: list[str] | None = None,
              crafts: dict | None = None) -> dict:
    """{"now": quests you can take (best EXP first), "soon": unlocking in the next levels,
    "town": the citizenship donations (repeatable, 100 items each), "done": count}.

    A quest finished only from a higher level ("Level 52+ to complete") counts at that level; one that asks a
    profession level the character doesn't have (crafts given) is left out."""
    done_set = set(done or [])
    now, soon, town = [], [], []
    open_ = availability.of(kb)
    for k, e in kb.entities.items():
        # only quests the KB confirms are in the game: none in Ossyria, no event the KB marks "Ended"
        if e.get("category") != "quest" or not open_.quest_open(k):
            continue
        q = quest(kb, k)
        if not q or (base_class and not job_fits(q, base_class, job)) or not craft_fits(q, crafts):
            continue
        if k in done_set:
            continue
        lv = q.opens_at()
        if level - WINDOW_BELOW <= lv <= level:
            (town if q.area == "Citizenship" else now).append(q)
        elif level < lv <= level + WINDOW_ABOVE:
            soon.append(q)
    now.sort(key=lambda q: (-q.exp, q.level))
    soon.sort(key=lambda q: (q.opens_at(), -q.exp))
    town.sort(key=lambda q: -q.exp)
    return {"now": now, "soon": soon, "town": town, "done": len(done_set)}


# ------------------------------------------------------------------ citizenship

TOWNS = ("Henesys", "Kerning City")          # the towns with citizenship (their donation boards in the KB)


def town_of(kb, q: Quest) -> str:
    """The citizenship town a quest belongs to: the town whose citizenship grade it requires, its board's town,
    else where its NPC stands (Jake and Mr. Goldstein's pages name no town, their quests ask Kerning's grade)."""
    if q.grade and q.grade[0] in TOWNS:
        return q.grade[0]
    m = re.search(r"\((.+)\)", q.npc or "")
    if m and m.group(1) in TOWNS:
        return m.group(1)
    key = kb._npc_by_name.get((q.npc or "").lower())
    page = kb.page(key) if key else ""
    hits = [(page.find(t), t) for t in TOWNS if t in page]
    return min(hits)[1] if hits else ""


def citizenship(kb, town: str, level: int, done: list[str] | None = None) -> list[Quest]:
    """The town's citizenship quests (donations and the rest) you can do now, best EXP first
    (one you can take but only complete at a higher level, "Level 52+ to complete", waits for that level)."""
    done_set = set(done or [])
    out = []
    open_ = availability.of(kb)
    for k, e in kb.entities.items():
        if e.get("category") != "quest" or k in done_set or not open_.quest_open(k):
            continue
        q = quest(kb, k)
        if q and q.area == "Citizenship" and q.opens_at() <= level and town_of(kb, q) == town:
            out.append(q)
    return sorted(out, key=lambda q: (-q.exp, q.level))
