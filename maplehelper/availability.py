"""What is in the live game, read from the knowledge base and nothing else.

The KB is the only source of truth, and the app shows only what it confirms. Nothing here is a list of places
or jobs: everything comes from data/kb at load time.

- The release guide (pages/guide/maplestory-classic-worlds-release-date.md) names what is confirmed for the
  game ("Confirmed content": "Classic maps on Maple Island and Victoria Island ...", "Forgotten Hollow", the
  confirmed bosses) and what is not ("Not at launch": "Ossyria and 3rd job are not initial-launch content").
  It also says that anything it doesn't confirm stays unconfirmed, and unconfirmed content is not shown.
- Every map page says which continent it is on ("Location Maple Road / Maple Island").
- NPC pages give the map they stand on, and quest pages give their NPC and whether the quest has "Ended".

When MeowDB updates those pages (say Ossyria opens), the next KB update brings the change to every player, and
the content appears without a new app version.
"""
from __future__ import annotations

import re

RELEASE_GUIDE = "guide/maplestory-classic-worlds-release-date"

_SECTION_END = re.compile(r"^(Level cap|Changes since|Preparing for launch|Not at launch|Confirmed content)\s*$", re.M)
_MAP_LOCATION = re.compile(r"^Location (.+?) / (.+?)\s*$", re.M)
_NPC_LOCATION = re.compile(r"^Location\n(.+?)\s*$", re.M)


def _section(text: str, head: str) -> str:
    """The text under a heading line of the release guide, up to the next known heading."""
    m = re.search(rf"^{re.escape(head)}\s*$", text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    end = _SECTION_END.search(rest)
    return rest[:end.start()] if end else rest


class Availability:
    def __init__(self, kb):
        self.kb = kb
        guide = kb.page(RELEASE_GUIDE) if kb.get(RELEASE_GUIDE) else ""
        # a KB with no release guide at all says nothing about what's out (a test's tiny KB): nothing is
        # filtered then. The real KB always has it (tools/kb_release.py refuses to publish one without it).
        self.known = bool(guide)
        self._memo: dict[tuple[str, str], object] = {}       # (what, key) -> answer: pages are read once
        # the guide's own body, not its FAQ/table of contents at the top (which repeats the headings)
        body = guide[guide.rfind("Confirmed content"):] if "Confirmed content" in guide else guide
        self.confirmed_text = _section(body, "Confirmed content")
        self.not_at_launch_text = _section(body, "Not at launch")
        # every map's continent and street, from its own page
        self.map_place: dict[str, tuple[str, str]] = {}       # "map name street" (as monster pages write it) -> ...
        self.map_place_by_name: dict[str, set[str]] = {}       # bare map name -> its continents
        self.continents: set[str] = set()
        self.streets: dict[str, set[str]] = {}                 # street -> continents it appears on
        for key, e in kb.entities.items():
            if e.get("category") != "map":
                continue
            m = _MAP_LOCATION.search(kb.page(key))
            if not m:
                continue
            street, continent = m.group(1).strip(), m.group(2).strip()
            name = e.get("name", "")
            self.map_place[f"{name} {street}"] = (continent, street)
            self.map_place_by_name.setdefault(name, set()).add(continent)
            self.continents.add(continent)
            self.streets.setdefault(street, set()).add(continent)
        self.confirmed = {c for c in self.continents if self._named(c, self.confirmed_text)}
        self.not_at_launch = {c for c in self.continents if self._named(c, self.not_at_launch_text)}
        self.confirmed -= self.not_at_launch
        # monsters the guide names one by one ("Confirmed bosses: Mushmom, Zombie Mushmom, ...", new monsters)
        names = sorted({e["name"] for e in kb.entities.values() if e.get("category") == "monster"}, key=len, reverse=True)
        text, self.named_monsters = self.confirmed_text, set()
        for n in names:                  # longest first: "King Slime" named doesn't name "Slime" too
            if self._named(n, text):
                self.named_monsters.add(n)
                text = re.sub(rf"(?<![\w-]){re.escape(n)}(?![\w-])", " ", text)
        third_out = bool(re.search(r"3rd job", self.not_at_launch_text, re.I))
        third_in = bool(re.search(r"3rd job", self.confirmed_text, re.I))
        # 3rd job opens only once the guide confirms it; until then (out, or not named at all) it stays shut
        self.job_tier = 3 if third_in and not third_out else 2

    @staticmethod
    def _named(name: str, text: str) -> bool:
        return bool(name) and re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text) is not None

    # ------------------------------------------------------------ maps

    def continent_of(self, map_cell: str) -> str | None:
        """The continent of a map as monster pages and NPC pages name it ("Snail Hunting Ground I Maple Road"),
        or a bare map name; None when the KB doesn't say."""
        hit = self.map_place.get(map_cell.strip())
        if hit:
            return hit[0]
        found = self.map_place_by_name.get(map_cell.strip())
        if found and len(found) == 1:
            return next(iter(found))
        return None

    def map_open(self, map_cell: str) -> bool:
        """A map the KB confirms is in the game. Unknown maps (no location in the KB) are not shown."""
        return not self.known or self.continent_of(map_cell) in self.confirmed

    def place_open(self, place: str) -> bool:
        """A town or street name ("El Nath", "Henesys", "Victoria Road"): open unless every continent it is on
        is unconfirmed. A name the KB has no map for at all is judged by the continents named in it."""
        if not self.known:
            return True
        conts = self.streets.get(place) or self.map_place_by_name.get(place)
        if conts:
            return bool(conts & self.confirmed)
        for c in self.continents - self.confirmed:
            if self._named(c, place):
                return False
        for street, cs in self.streets.items():
            if not cs & self.confirmed and self._named(street, place):
                return False
        return True

    # ------------------------------------------------------------ monsters, NPCs, quests

    def monster_open(self, name: str, map_cells: list[str]) -> bool:
        if not self.known:
            return True
        return name in self.named_monsters or any(self.map_open(m) for m in map_cells)

    def _once(self, what: str, key: str, work):
        k = (what, key)
        if k not in self._memo:
            self._memo[k] = work()
        return self._memo[k]

    def monster_key_open(self, key: str) -> bool:
        e = self.kb.get(key)
        if not e:
            return False
        return self._once("monster", key, lambda: self.monster_open(e.get("name", ""), self.kb.all_maps(key)))

    def npc_continent(self, key: str) -> str | None:
        def work():
            m = _NPC_LOCATION.search(self.kb.page(key))
            return self.continent_of(m.group(1)) if m else None
        return self._once("npc", key, work)

    def npc_open(self, key: str) -> bool:
        return not self.known or self.npc_continent(key) in self.confirmed

    def quest_open(self, key: str) -> bool:
        if not self.known:
            return True
        return self._once("quest", key, lambda: self._quest_open(key))

    def _quest_open(self, key: str) -> bool:
        e = self.kb.get(key) or {}
        page = self.kb.page(key)
        if re.search(r"^Ended\s*$", page, re.M):
            return False
        props = e.get("props") or {}
        # the quest's own area first: the El Nath storyline handed out by Victoria's job instructors is El Nath's
        if not self.place_open(str(props.get("Area") or "")):
            return False
        npc = self.kb.npc_key(str(props.get("NPC") or "")) if hasattr(self.kb, "npc_key") else None
        where = self.npc_continent(npc) if npc else None
        return where in self.confirmed if where else True

    # ------------------------------------------------------------ jobs

    def job_tier_open(self, tier: int) -> bool:
        return tier <= self.job_tier

    # ------------------------------------------------------------ for the AI

    def scope_note(self) -> str:
        """The game's scope as the KB states it, for the AI's prompt."""
        shut = sorted(self.continents - self.confirmed)
        parts = [f"Released and confirmed by the knowledge base: {', '.join(sorted(self.confirmed)) or 'nothing'}."]
        if shut:
            parts.append(f"NOT in the game (the KB does not confirm them): {', '.join(shut)} — never send the player "
                         "there, never suggest their maps, monsters, NPCs or quests, and if asked say they are not in "
                         "the game yet.")
        if self.job_tier < 3:
            parts.append("3rd job advancement is not in the game; never present 3rd-job jobs or skills as available.")
        parts.append("Anything the KB does not confirm is not in the game: say so instead of guessing.")
        return " ".join(parts)


def of(kb) -> Availability:
    """The availability for this knowledge base, worked out once per KB object (a KB update loads a new one)."""
    a = getattr(kb, "_availability", None)
    if a is None or a.kb is not kb:
        a = Availability(kb)
        try:
            kb._availability = a
        except AttributeError:     # a KB stand-in that takes no attributes: worked out each time
            pass
    return a
