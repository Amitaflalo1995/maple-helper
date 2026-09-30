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

from .store import kb_dir

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
        return None

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
