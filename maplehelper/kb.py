"""Local knowledge base: entity index, name/alias lookup and pre-retrieval for questions.

Pre-retrieval matters for speed: the app hands Claude the pages it will most
likely need (entities named in the question, monsters around the player's
level), so most answers need no tool round-trips at all.
"""
from __future__ import annotations

import json
import re
from functools import cached_property
from pathlib import Path

from . import bidi
from .store import ASSETS, kb_dir

FALLBACK_DIR = ASSETS / "fallback"
CLASS_PICTURE_FALLBACK = {
    "crusader": "fighter", "white-knight": "page", "dragon-knight": "spearman", "f-p-mage": "f-p-wizard",
    "i-l-mage": "i-l-wizard", "priest": "cleric", "ranger": "hunter", "sniper": "crossbowman",
    "hermit": "assassin", "chief-bandit": "bandit",
}

HEBREW = re.compile(r"[֐-׿]")


_FINALS = str.maketrans("ךםןףץ", "כמנפצ")
# Hebrew geresh / gershayim and the other look-alikes a phone or a keyboard types: "ג׳וניור" = "ג'וניור"
_QUOTES = str.maketrans({"׳": "'", "`": "'", "´": "'", "’": "'", "‘": "'", "״": '"', "“": '"', "”": '"'})


def fold_quotes(s: str) -> str:
    return s.translate(_QUOTES)


def _heb_letters(s: str) -> int:
    return len(re.findall(r"[א-ת]", s))


def _heb_loose(s: str) -> str:
    """Spelling-tolerant Hebrew: final letters, doubled yod/vav and a word-final he/alef don't matter
    ("אלינייה" = "אליניה", "הנסיס" = "הניסיס" is left to the alias list)."""
    s = s.translate(_FINALS)
    s = re.sub(r"יי+", "י", s)
    s = re.sub(r"וו+", "ו", s)
    return re.sub(r"(?<=[א-ת])[הא](?=\s|$)", "", s)


def _no_article(s: str) -> str:
    """The definite article off every word: "החילזון האדום" = "חילזון אדום" (used only for long aliases:
    "הנהר" is "the river", not River)."""
    return re.sub(r"(?:(?<=\s)|^)ה(?=[א-ת]{3,})", "", s)


def _norm(s: str) -> str:
    s = fold_quotes(s.lower())
    # gershayim inside a Hebrew word stays ("צה"ל"); any other double quote is punctuation
    s = re.sub(r'(?<![א-ת])"|"(?![א-ת])', " ", s)
    s = re.sub(r"[^\w֐-׿'\" ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# aliases.json ships with the knowledge base release: its few bad entries are corrected here, in code.
# Common Hebrew words and generic nouns an alias must never be ("מאי" is May, "פסל" any statue, "השף" any chef):
ALIAS_DROP = {
    "בין", "אלי", "אליי", "מאי", "פי", "סר", "מקס", "אוק", "פיל", "הפיל",
    "נהר", "הנהר", "פסל", "סדן", "צור", "הצור", "השף", "שף", "רוח רפאים", "טוויטר", "טיק טוק", "שוער", "ליצן",
    "תיבת אוצר",
}
# alias -> entity key, over aliases.json (keys and names as in the KB's index.json)
ALIAS_SET = {
    "פטרייה רקובה": "monster/62",        # Rotten Mushroom (aliases.json gave this spelling to Rotten Mushmom)
    "לטי": "monster/1011",               # Leatty (aliases.json: Dark Leatty, which keeps "דארק ליטי")
    "ליטי": "monster/1011",
    "ג'וניור סנטינל": "monster/1001",     # Jr. Sentinel, not the Maple Island "Tutorial Jr. Sentinel"
    # the KB has "Jr. Boogie 1" and "Jr. Boogie 2" (the same stats and maps), no plain "Jr. Boogie"
    "jr boogie": "monster/33", "ג'וניור בוגי": "monster/33",
}
# NPCs of the KB named like an everyday English word: an answer saying "Max HP" or "River" at a sentence start
# names no NPC (the AI lists the NPCs it means in its META entities, those still get a card)
COMMON_WORD_NPCS = {"Max", "River", "Anvil", "Oak", "Jack", "Pan", "Chef", "Statue", "Flint", "Rain", "Exit", "Silver"}
NO_LOOSE_UNDER = 5    # Hebrew letters an alias needs for its spelling-tolerant form ("פיה" -> "פי" is no name)
PREFIX_FROM = 4        # Hebrew letters a name needs before a glued prefix counts ("לאן" is not ל + "אן")
_PREFIX = "[בלמהושכ]{1,2}"


class KnowledgeBase:
    def __init__(self, root: Path | None = None):
        self.root = root or kb_dir()
        self.entities: dict[str, dict] = {}
        idx = self.root / "index.json"
        if idx.exists():
            for e in json.loads(idx.read_text(encoding="utf-8")):
                self.entities[e["key"]] = e
        self.aliases: dict[str, str] = {}   # normalized alias -> key
        alias_file = self.root / "aliases.json"
        if alias_file.exists():
            for key, names in json.loads(alias_file.read_text(encoding="utf-8")).items():
                for n in names:
                    if _norm(n) not in ALIAS_DROP:
                        self.aliases[_norm(n)] = key
        self.aliases.update({_norm(a): k for a, k in ALIAS_SET.items() if k in self.entities})
        # names with ", " ": " or "[ ]" ("Tree Dungeon, Monkey Forest I") stay one block in a Hebrew answer
        bidi.set_names(e.get("name", "") for e in self.entities.values())

    # ------------------------------------------------------------ basic access

    def get(self, key: str) -> dict | None:
        return self.entities.get(key)

    def image_path(self, key: str) -> Path | None:
        e = self.get(key)
        if e and e.get("image"):
            p = self.root / e["image"]
            return p if p.exists() else None
        if e and e["category"] == "quest":
            # a quest shows the NPC who gives it
            giver = str((e.get("props") or {}).get("NPC") or "").lower()
            npc = self._npc_by_name.get(giver) or self._npc_by_name.get(re.sub(r"\s*\(.*?\)", "", giver))
            if npc and self.image_path(npc):
                return self.image_path(npc)
        if e and e["category"] == "class":
            # 3rd jobs have no picture: use the 2nd job they come from
            second = CLASS_PICTURE_FALLBACK.get(key.partition("/")[2])
            if second and self.get(f"class/{second}"):
                return self.image_path(f"class/{second}")
        return None

    def picture(self, key: str) -> Path | None:
        """Always a picture for a card: the entity's own, a related one, or its category icon."""
        own = self.image_path(key)
        if own:
            return own
        cat = key.partition("/")[0]
        fb = FALLBACK_DIR / f"{cat}.png"
        return fb if fb.exists() else (FALLBACK_DIR / "default.png")

    @cached_property
    def _npc_by_name(self) -> dict[str, str]:
        out = {}
        for k, e in self.entities.items():
            if e["category"] == "npc":
                n = e["name"].lower()
                out.setdefault(n, k)
                out.setdefault(re.sub(r"\s*\(.*?\)", "", n), k)
        return out

    def npc_key(self, name: str) -> str | None:
        """The NPC page for a name as quests write it ("Arwen the Fairy", "Jake (Subway)")."""
        n = (name or "").strip().lower()
        return self._npc_by_name.get(n) or self._npc_by_name.get(re.sub(r"\s*\(.*?\)", "", n)) if n else None

    def all_maps(self, key: str) -> list[str]:
        """Every map cell of a monster page's "Map Locations" table ("Snail Hunting Ground I Maple Road")."""
        return self._top_maps(key, 999)

    def page(self, key: str) -> str:
        e = self.get(key)
        if not e:
            return ""
        cat, _, slug = key.partition("/")
        p = self.root / "pages" / cat / f"{slug}.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def page_body(self, key: str, limit: int = 2500) -> str:
        text = self.page(key)
        if text.startswith("---"):
            end = text.find("\n---", 3)
            text = text[end + 4:] if end > 0 else text
        return text.strip()[:limit]

    # ------------------------------------------------------------ name lookup

    @cached_property
    def _names(self) -> list[tuple[str, str, bool]]:
        """(normalized name, key, loose) sorted longest-first, so 'Red Snail' wins over 'Snail'.

        loose=True is a long Hebrew alias's spelling-tolerant form, looked up in the question's loose copies;
        a loose form two entities share, or that is another entity's exact name, is dropped (ambiguous)."""
        pairs = []
        for key, e in self.entities.items():
            n = _norm(e["name"])
            if len(n) >= 3:
                pairs.append((n, key, False))
        pairs += [(a, k, False) for a, k in self.aliases.items() if len(a) >= 2]
        exact = {n: k for n, k, _ in pairs}
        loose: dict[str, set[str]] = {}
        for a, k in self.aliases.items():
            if HEBREW.search(a) and _heb_letters(a) >= NO_LOOSE_UNDER:
                form = _heb_loose(a)
                if _heb_letters(form) >= 3 and form not in ALIAS_DROP:
                    loose.setdefault(form, set()).add(k)
        pairs += [(f, next(iter(ks)), True) for f, ks in loose.items()
                  if len(ks) == 1 and exact.get(f, next(iter(ks))) in ks]
        return sorted(pairs, key=lambda p: -len(p[0]))

    def _occurrence(self, hay: str, name: str, key: str, taken: list[tuple[int, int]]) -> tuple[int, int] | None:
        """The first place `name` stands in `hay` (" word word ... ") outside the spans already taken, as a
        (first word, last word + 1) range. Hebrew prefixes glue on to a long enough name ("לחילזון", "בהנסיס"),
        and a monster's name may be plural ("fire boars", "תמנונים")."""
        if name not in hay:
            return None          # cheap: most names aren't in the question at all
        heb = bool(HEBREW.search(name))
        pre = f"(?:{_PREFIX})?" if heb and _heb_letters(name) >= PREFIX_FROM else ""
        plural = ""
        if key.startswith("monster/"):
            plural = "(?:ימ|ות|ים)?" if heb else "(?:e?s)?"
        for m in re.finditer(f"(?<= ){pre}{re.escape(name)}{plural}(?= )", hay):
            w0 = hay.count(" ", 0, m.start()) - 1
            span = (w0, w0 + name.count(" ") + 1)
            if not any(a < span[1] and span[0] < b for a, b in taken):
                return span
        return None

    def mention_spans(self, text: str, max_results: int = 5, answer: bool = False) -> list[tuple[str, int, int]]:
        """(key, first word, last word + 1) of the entities named in free text, by the words of _norm(text).

        The text is searched as typed, and (Hebrew) in two loose copies: spelling-tolerant, and that without the
        definite article. The copies keep the words in place, so a name matched in one copy can't be counted
        again from another, nor a shorter name inside it ("Red Snail" is not also "Snail").

        answer=True reads an AI answer, where game names are written exactly: English names must match their
        case ("your max HP" is not Max, "the river" not River), no loose Hebrew forms, no English aliases, and
        an NPC named like an everyday word (COMMON_WORD_NPCS) never counts."""
        norm = _norm(text)
        copies = [f" {norm} "]
        if HEBREW.search(norm) and not answer:
            loose = _heb_loose(norm)
            copies += [f" {loose} ", f" {_no_article(loose)} "]
        out: list[tuple[str, int, int]] = []
        taken: list[tuple[int, int]] = []
        for name, key, is_loose in self._names:
            for i, hay in enumerate(copies):
                if (i > 0) != is_loose:
                    continue      # exact names in the text as typed; loose forms in the loose copies
                span = self._occurrence(hay, name, key, taken)
                if span and not HEBREW.search(name) and (answer or key in self._common_npcs) \
                        and not self._written(text, key, name, answer):
                    span = None       # a question's "max level" is no Max either; "where is Max" is
                if span:
                    taken.append(span)
                    if key not in [k for k, _, _ in out]:
                        out.append((key, *span))
                    break
            if len(out) >= max_results:
                break
        return out

    @cached_property
    def _common_npcs(self) -> set[str]:
        return {k for k, e in self.entities.items() if e.get("category") == "npc" and e.get("name") in COMMON_WORD_NPCS}

    def _written(self, text: str, key: str, name: str, answer: bool = True) -> bool:
        """An English entity name written as the game writes it (its own case). In an answer an NPC named like an
        everyday word never counts (the AI lists the ones it means)."""
        e = self.get(key) or {}
        if _norm(e.get("name", "")) != name or answer and key in self._common_npcs:
            return False          # an English alias, or an everyday word
        words = re.escape(fold_quotes(e["name"])).replace(r"\ ", r"\s+")
        plural = "(?:e?s)?" if key.startswith("monster/") else ""
        return re.search(rf"(?<![\w]){words}{plural}(?![\w])", fold_quotes(text)) is not None

    def find_mentions(self, text: str, max_results: int = 5, answer: bool = False) -> list[str]:
        """Entities named in free text (English names, Hebrew aliases, transliterations); answer=True for an AI
        answer's text (exact names only, see mention_spans)."""
        return [k for k, _, _ in self.mention_spans(text, max_results, answer)]

    @cached_property
    def _resolve_pattern(self) -> re.Pattern | None:
        """One pattern for every Hebrew alias, longest first (compiling one per alias took ~140 ms a call).
        A glued prefix only before a long alias: "כאן" is not כ + "אן" (Anne), "מפיל" not מ + "פיל"."""
        heb = sorted((a for a, k in self.aliases.items() if HEBREW.search(a) and self.get(k)), key=len, reverse=True)
        if not heb:
            return None
        long = [a for a in heb if _heb_letters(a) >= PREFIX_FROM]
        alt = "|".join(map(re.escape, heb))
        pre = rf"(?P<pre>[ובלמהשכ]{{1,2}}(?=(?:{'|'.join(map(re.escape, long))})(?![֐-׿])))?" if long else ""
        return re.compile(rf"(?<![֐-׿]){pre}(?P<name>{alt})(?![֐-׿])")

    def resolve_names(self, text: str) -> str:
        """Replace Hebrew aliases/transliterations with official English names (used after speech-to-text).
        The same safety as find_mentions: no dropped alias (ALIAS_DROP), a glued prefix only on a long name."""
        out = fold_quotes(text)
        if not HEBREW.search(out) or self._resolve_pattern is None:
            return out

        def name(m: re.Match) -> str:
            # keep a glued Hebrew prefix: "ובלו סנייל" → "ו-Blue Snail"
            en = self.get(self.aliases[m.group("name")])["name"]
            pre = m.groupdict().get("pre")
            return f"{pre}-{en}" if pre else en

        return self._resolve_pattern.sub(name, out)

    # ------------------------------------------------------------ drops

    @cached_property
    def _item_by_name(self) -> dict[str, str]:
        out = {}
        for k, e in self.entities.items():
            if e["category"] == "item":
                out.setdefault(e["name"].strip().lower(), k)
        return out

    def monster_drops(self, key: str) -> list[str]:
        """Item keys a monster drops, read from its page (confirmed Classic drops + MSEA reference list)."""
        body = self.page(key)
        i = body.find("Drops (MS Classic)")
        if i < 0:
            return []
        end = len(body)
        for marker in ("Associated Quests", "Map Locations"):
            j = body.find(marker, i)
            if 0 < j < end:
                end = j
        found = []
        for line in body[i:end].split("\n"):
            k = self._item_by_name.get(line.strip().lower())
            if k and k not in found:
                found.append(k)
        return found

    @cached_property
    def droppers(self) -> dict[str, list[str]]:
        """item key → monster keys that drop it (lowest level first): only monsters the KB confirms are in the
        game (availability.py), so no Orbis/El Nath or map-less monster is ever named as a source."""
        from . import availability
        open_ = availability.of(self)
        out: dict[str, list[str]] = {}
        for mkey, e in self.entities.items():
            if e["category"] == "monster" and open_.monster_key_open(mkey):
                for ikey in self.monster_drops(mkey):
                    out.setdefault(ikey, []).append(mkey)
        lvl = lambda k: (self.get(k).get("props") or {}).get("Level") or 999  # noqa: E731
        return {i: sorted(ms, key=lvl) for i, ms in out.items()}

    def drop_groups(self, item_keys: list[str], limit: int = 8) -> list[dict]:
        """Group items by the monsters that drop them: [{"monster": key, "items": [keys]}], by monster level."""
        groups: dict[str, list[str]] = {}
        for i in item_keys:
            for m in self.droppers.get(i, []):
                groups.setdefault(m, [])
                if i not in groups[m]:
                    groups[m].append(i)
        lvl = lambda k: (self.get(k).get("props") or {}).get("Level") or 999  # noqa: E731
        ordered = sorted(groups, key=lvl)[:limit]
        return [{"monster": m, "items": groups[m]} for m in ordered]

    def ensure_drop_table(self) -> None:
        """Write drops.tsv next to index.json so Claude can grep 'which monsters drop X' in one step: only monsters
        the KB confirms are in the game. A table from before that rule (no drops.ingame mark beside it) is redone."""
        path = self.root / "drops.tsv"
        mark = self.root / "drops.ingame"
        idx = self.root / "index.json"
        try:
            if (path.exists() and mark.exists() and idx.exists()
                    and path.stat().st_mtime >= idx.stat().st_mtime):
                return
            mark.write_text("drops.tsv lists only monsters the KB confirms are in the game (availability.py)\n",
                            encoding="utf-8")
            lines = ["monster\tmonster_level\tmonster_key\titem\titem_type\titem_key"]
            for ikey, monsters in self.droppers.items():
                it = self.get(ikey)
                for m in monsters:
                    me = self.get(m)
                    lv = (me.get("props") or {}).get("Level", "")
                    lines.append(f"{me['name']}\t{lv}\t{m}\t{it['name']}\t{it.get('type') or ''}\t{ikey}")
            path.write_text("\n".join(lines), encoding="utf-8")
        except OSError:
            pass

    def drops_digest(self, key: str) -> str:
        drops = self.monster_drops(key)
        if not drops:
            return ""
        e = self.get(key)
        names = ", ".join(f"{self.get(k)['name']} [{k}]" for k in drops)
        return f"Drops of {e['name']} (MSEA reference list; names and keys exactly as in the game): {names}"

    # ------------------------------------------------------------ level digest

    @cached_property
    def _monsters(self) -> list[dict]:
        """The monsters the KB confirms are in the game, with their confirmed maps (the AI's level digest)."""
        from . import availability
        open_ = availability.of(self)
        rows = []
        for key, e in self.entities.items():
            if e["category"] != "monster" or not open_.monster_key_open(key):
                continue
            p = e.get("props", {})
            lvl = p.get("Level")
            if not isinstance(lvl, (int, float)):
                continue
            rows.append({"key": key, "name": e["name"], "level": int(lvl), "hp": p.get("HP"),
                         "exp": p.get("EXP"), "maps": [m for m in self.all_maps(key) if open_.map_open(m)][:3]})
        return sorted(rows, key=lambda r: r["level"])

    def _top_maps(self, key: str, n: int = 3) -> list[str]:
        body = self.page(key)
        i = body.find("Map Locations")
        if i < 0:
            return []
        maps = []
        # table rows: "Map Region | Count | Share | Types | Mob Rate | Respawn"
        for line in body[i:].split("\n")[2:2 + n * 3]:
            if " | " not in line:
                break  # end of the table: the "Change history" table below it has numeric rows too ("HP | 7,560 | ...")
            cols = [c.strip() for c in line.split(" | ")]
            if len(cols) >= 3 and cols[1].isdigit():
                maps.append(cols[0])
            if len(maps) >= n:
                break
        return maps

    @cached_property
    def _regions(self) -> list[str]:
        """The regions the map pages name ("Location Maple Road / Maple Island" → "Maple Road"), longest first."""
        found = set()
        for p in (self.root / "pages" / "map").glob("*.md"):
            m = re.search(r"^Location (.+?) / ", p.read_text(encoding="utf-8"), re.M)
            if m:
                found.add(m.group(1).strip())
        return sorted(found, key=len, reverse=True)

    def map_label(self, raw: str) -> str:
        """A monster page's map cell glues the region to the map's name ("Snail Hunting Ground I Maple Road"):
        "Snail Hunting Ground I · Maple Road" when it ends with a known region, else as it is."""
        for region in self._regions:
            name = raw[:-len(region)].rstrip()
            if raw.endswith(" " + region) and name:
                return f"{name} · {region}"
        return raw

    def level_digest(self, level: int, below: int = 5, above: int = 8) -> str:
        rows = [r for r in self._monsters if level - below <= r["level"] <= level + above]
        if not rows:
            return ""
        lines = ["Monsters near the player's level (name | level | HP | EXP | top maps | key):"]
        for r in rows[:40]:
            lines.append(f"{r['name']} | {r['level']} | {r['hp']} | {r['exp']} | {', '.join(r['maps'])} | {r['key']}")
        return "\n".join(lines)
