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

from .store import ASSETS, kb_dir

FALLBACK_DIR = ASSETS / "fallback"
CLASS_PICTURE_FALLBACK = {
    "crusader": "fighter", "white-knight": "page", "dragon-knight": "spearman", "f-p-mage": "f-p-wizard",
    "i-l-mage": "i-l-wizard", "priest": "cleric", "ranger": "hunter", "sniper": "crossbowman",
    "hermit": "assassin", "chief-bandit": "bandit",
}

HEBREW = re.compile(r"[֐-׿]")


_FINALS = str.maketrans("ךםןףץ", "כמנפצ")


def _heb_loose(s: str) -> str:
    """Spelling-tolerant Hebrew: final letters, doubled yod/vav and a word-final he/alef don't matter
    ("אלינייה" = "אליניה", "הנסיס" = "הניסיס" is left to the alias list)."""
    s = s.translate(_FINALS)
    s = re.sub(r"יי+", "י", s)
    s = re.sub(r"וו+", "ו", s)
    s = re.sub(r"(?<=[א-ת])[הא](?=\s|$)", "", s)
    # definite article on every word: "החילזון האדום" = "חילזון אדום"
    s = re.sub(r"(?:(?<=\s)|^)ה(?=[א-ת]{3,})", "", s)
    return s


def _norm(s: str) -> str:
    s = s.lower().replace("’", "'")
    s = re.sub(r"[^\w֐-׿' ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


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
                    self.aliases[_norm(n)] = key

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
    def _names(self) -> list[tuple[str, str]]:
        """(normalized name, key) sorted longest-first, so 'Red Snail' wins over 'Snail'."""
        pairs = []
        for key, e in self.entities.items():
            n = _norm(e["name"])
            if len(n) >= 3:
                pairs.append((n, key))
        pairs += [(a, k) for a, k in self.aliases.items() if len(a) >= 2]
        pairs += [(_heb_loose(a), k) for a, k in self.aliases.items() if len(a) >= 3 and _heb_loose(a) != a]
        return sorted(pairs, key=lambda p: -len(p[0]))

    def find_mentions(self, text: str, max_results: int = 5) -> list[str]:
        """Entities named in free text (English names, Hebrew aliases, transliterations)."""
        norm = _norm(text)
        hay = f" {norm} {_heb_loose(norm)} " if HEBREW.search(norm) else f" {norm} "
        found: list[str] = []
        taken: list[tuple[int, int]] = []
        for name, key in self._names:
            i = hay.find(f" {name} ")
            if i < 0 and HEBREW.search(name) and len(name) >= 4:
                # Hebrew prefixes: ב/ל/מ/ה/ו/ש/כ glued to the word ("לחילזון", "בהנסיס")
                m = re.search(r"[ ][בלמהושכ]{1,2}" + re.escape(name) + r"[ ]", hay)
                i = m.start() if m else -1
            if i < 0:
                continue
            span = (i, i + len(name) + 2)
            if any(a < span[1] and span[0] < b for a, b in taken):
                continue  # inside a longer name already matched
            taken.append(span)
            if key not in found:
                found.append(key)
            if len(found) >= max_results:
                break
        return found

    def resolve_names(self, text: str) -> str:
        """Replace Hebrew aliases/transliterations with official English names (used after speech-to-text)."""
        out = text
        for alias, key in sorted(self.aliases.items(), key=lambda p: -len(p[0])):
            if not HEBREW.search(alias):
                continue
            e = self.get(key)
            if e:
                # keep a glued Hebrew prefix: "ובלו סנייל" → "ו-Blue Snail"
                name = e["name"]
                out = re.sub(rf"(?<![֐-׿])([ובלמהשכ]{{0,2}}){re.escape(alias)}(?![֐-׿])",
                             lambda m, n=name: f"{m.group(1)}-{n}" if m.group(1) else n, out)
        return out

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
        """item key → monster keys that drop it (lowest level first)."""
        out: dict[str, list[str]] = {}
        for mkey, e in self.entities.items():
            if e["category"] == "monster":
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
        """Write drops.tsv next to index.json so Claude can grep 'which monsters drop X' in one step."""
        path = self.root / "drops.tsv"
        idx = self.root / "index.json"
        try:
            if path.exists() and idx.exists() and path.stat().st_mtime >= idx.stat().st_mtime:
                return
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
        rows = []
        for key, e in self.entities.items():
            if e["category"] != "monster":
                continue
            p = e.get("props", {})
            lvl = p.get("Level")
            if not isinstance(lvl, (int, float)):
                continue
            rows.append({"key": key, "name": e["name"], "level": int(lvl), "hp": p.get("HP"),
                         "exp": p.get("EXP"), "maps": self._top_maps(key)})
        return sorted(rows, key=lambda r: r["level"])

    def _top_maps(self, key: str, n: int = 3) -> list[str]:
        body = self.page(key)
        i = body.find("Map Locations")
        if i < 0:
            return []
        maps = []
        # table rows: "Map Region | Count | Share | Types | Mob Rate | Respawn"
        for line in body[i:].split("\n")[2:2 + n * 3]:
            cols = [c.strip() for c in line.split(" | ")]
            if len(cols) >= 3 and cols[1].isdigit():
                maps.append(cols[0])
            if len(maps) >= n:
                break
        return maps

    def level_digest(self, level: int, below: int = 5, above: int = 8) -> str:
        rows = [r for r in self._monsters if level - below <= r["level"] <= level + above]
        if not rows:
            return ""
        lines = ["Monsters near the player's level (name | level | HP | EXP | top maps | key):"]
        for r in rows[:40]:
            lines.append(f"{r['name']} | {r['level']} | {r['hp']} | {r['exp']} | {', '.join(r['maps'])} | {r['key']}")
        return "\n".join(lines)
