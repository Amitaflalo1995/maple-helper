"""The KB's guides as a small library: categories, "for you" picks, and a clean reading view.

The scraped pages carry the source site's menus and ads around the article; `parse` keeps the
article (title, intro, pros/cons, sections, tables) so the reader shows only the guide.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass, field

from . import bidi
from .store import ASSETS, DATA_DIR

SUMMARIES = DATA_DIR / "guide_summaries"
TRANSLATIONS = ASSETS / "guides"     # <lang>/<slug>.json, translated once and shipped with the app
CATEGORIES = ["for_you", "classes", "leveling", "mechanics", "general"]
LEVELING = {"best-grind-maps-every-level", "exp-table-level-1-to-100", "hp-mp-gain-explained",
            "kerning-city-party-quest-kpq-guide", "beginners-guide-first-steps-in-maple-world",
            "forgotten-hollow-the-new-endgame-area"}
MECHANICS = {"explaining-the-damage-formula", "attack-speed-and-animation-times", "attacks-you-can-use-mid-jump",
             "spawn-engine-respawn-and-map-capacity", "speed-jump-and-movement", "weapon-reach", "class-dps-rankings"}
JUNK = ("Explore the database", "Items Monsters Maps", "Plan your character", "Your shortcuts", "Watchlist ›",
        "Free Market", "Guides Tier List", "[ Notice ]", "Ad blocked?", "Buy us a coffee", "Home / MS Classic",
        "← All guides")


@dataclass
class Guide:
    key: str
    title: str
    intro: str = ""
    minutes: int | None = None
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    sections: list[tuple[str, list[str]]] = field(default_factory=list)   # (heading, lines)

    @property
    def slug(self) -> str:
        return self.key.split("/", 1)[1]


def category(key: str) -> str:
    slug = key.split("/", 1)[1]
    if slug.endswith("-class-guide"):
        return "classes"
    if slug in LEVELING:
        return "leveling"
    if slug in MECHANICS:
        return "mechanics"
    return "general"


def _norm(line: str) -> str:
    """Headings are written slightly differently in the contents ("and" / "&", capitals)."""
    return re.sub(r"\s+", " ", line.lower().replace("&", "and")).strip()


def _junk(line: str) -> bool:
    return line in ("›", "Guides", "Contents") or line.startswith(JUNK)


def parse(key: str, page: str) -> Guide:
    lines = [ln.strip() for ln in page.split("\n---", 2)[-1].splitlines()]
    title = next((ln[2:] for ln in lines if ln.startswith("# ")), key)
    g = Guide(key, title)
    body_start = next((i for i, ln in enumerate(lines) if ln.startswith("# ")), 0) + 1
    intro = next((ln for ln in lines[body_start:] if ln and not _junk(ln)), "")
    g.intro = intro
    m = re.search(r"(\d+) min read", page)
    g.minutes = int(m.group(1)) if m else None

    # the contents list ends where its first heading starts again; a nested heading may share a
    # line with its parent ("Starting at level 30 Recommended citizenship")
    toc: list[str] = []
    if "Contents" in lines:
        i = lines.index("Contents") + 1
        while i < len(lines) and lines[i] and not (toc and _norm(toc[0]).startswith(_norm(lines[i]))):
            toc.append(_norm(lines[i]))
            i += 1
        pre, body = lines[body_start:lines.index("Contents")], lines[i:]
    else:
        pre, body = [], lines[body_start + 1:]

    # pros / cons sit before the contents on class guides ("Pros" alone, or "Pros <first one>")
    bucket = None
    for ln in pre:
        head, _, rest = ln.partition(" ")
        if head in ("Pros", "Cons"):
            bucket = g.pros if head == "Pros" else g.cons
            if rest:
                bucket.append(rest)
        elif bucket is not None and ln and not _junk(ln):
            bucket.append(ln)

    def is_heading(ln: str) -> bool:
        n = _norm(ln)
        return any(t == n or t.startswith(n + " ") or t.endswith(" " + n) for t in toc)

    current: tuple[str, list[str]] | None = None
    for ln in body:
        if not ln or _junk(ln):
            continue
        if is_heading(ln):
            current = (ln, [])
            g.sections.append(current)
        elif current is not None:
            current[1].append(ln)
    if not g.sections and body:
        g.sections.append(("", [ln for ln in body if ln and not _junk(ln)]))
    return g


def _cell(text: str, rtl: bool) -> str:
    """Escaped text; in a Hebrew guide, English names and numbers stay whole blocks."""
    # any Hebrew in it makes it a Hebrew line, even when it opens with an English name ("Warrior, ג'וב 1")
    return html.escape(bidi.plain(text, True) if rtl and bidi._RTL.search(text) else text)


def _table_html(rows: list[list[str]], rtl: bool = False) -> str:
    head, *body = rows
    attrs = " dir='rtl' align='right'" if rtl else ""
    cell = "<p dir='rtl' align='right' style='margin:0'>{}</p>" if rtl else "{}"     # Qt sets direction per paragraph
    return (f"<table cellspacing='0' cellpadding='4'{attrs}><tr>"
            + "".join(f"<th>{cell.format(_cell(c, rtl))}</th>" for c in head) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{cell.format(_cell(c, rtl))}</td>" for c in r) + "</tr>" for r in body)
            + "</table>")


def to_html(g: Guide, labels: dict, rtl: bool = False) -> str:
    """Readable HTML for QTextBrowser: headings, paragraphs, and real tables for "a | b | c" rows.
    A Hebrew guide reads right to left, with English game names kept as whole blocks."""
    side = " dir='rtl' align='right'" if rtl else ""
    out = []

    def para(text: str) -> str:
        return bidi.paragraph_html(text, "rtl" if rtl and bidi.direction(text) == "rtl" else None)
    if g.intro:
        out.append(f"<p{side}><i>{_cell(g.intro, rtl)}</i></p>")
    for name, items in ((labels["pros"], g.pros), (labels["cons"], g.cons)):
        if items:
            out.append(f"<h3{side}>{html.escape(name)}</h3><ul{side}>"
                       + "".join(f"<li>{_cell(i, rtl)}</li>" for i in items) + "</ul>")
    for heading, lines in g.sections:
        if heading:
            out.append(f"<h3{side}>{_cell(heading, rtl)}</h3>")
        table: list[list[str]] = []
        for ln in lines:
            if " | " in ln:
                # some tables open with an empty icon column: "| Skill | Class | ..."
                table.append([c.strip() for c in ln.strip().strip("|").split(" | ")])
                continue
            if table:
                out.append(_table_html(table, rtl))
                table = []
            out.append(para(ln))
        if table:
            out.append(_table_html(table, rtl))
    return "\n".join(out)


def page_hash(page: str) -> str:
    return hashlib.sha1(page.encode("utf-8")).hexdigest()[:12]


def translation(key: str, lang: str) -> dict | None:
    """The shipped translation of a guide, or None (English is the original)."""
    if lang == "en":
        return None
    path = TRANSLATIONS / lang / f"{key.split('/', 1)[1]}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def localized(key: str, page: str, lang: str) -> tuple[Guide, bool, bool]:
    """(guide in the player's language when translated, translated?, English changed since the translation?)"""
    tr = translation(key, lang)
    if not tr:
        return parse(key, page), False, False
    g = Guide(key, tr.get("title") or key, tr.get("intro", ""), parse(key, page).minutes, tr.get("pros", []),
              tr.get("cons", []), [(s.get("heading", ""), s.get("lines", [])) for s in tr.get("sections", [])])
    return g, True, tr.get("source_hash") != page_hash(page)


def title(key: str, fallback: str, lang: str) -> str:
    tr = translation(key, lang)
    return (tr or {}).get("title") or fallback


def text_of(key: str, lang: str) -> str:
    """All the translated text of a guide, for search."""
    tr = translation(key, lang)
    return json.dumps(tr, ensure_ascii=False) if tr else ""


def all_guides(kb) -> list[dict]:
    """[{key, title, category, minutes}] for every guide in the KB, sorted by title."""
    out = []
    for key, e in kb.entities.items():
        if e.get("category") == "guide":
            m = re.search(r"(\d+) min read", kb.page(key)[:6000])
            out.append({"key": key, "title": e.get("name", key), "category": category(key),
                        "minutes": int(m.group(1)) if m else None})
    return sorted(out, key=lambda g: g["title"])


def for_you(kb, c) -> list[str]:
    """The guides that fit this character right now, most useful first."""
    from . import plan
    picks = []
    if c:
        picks.append(plan.class_guide(kb, c.base_class, c.job))
        picks.append(plan.class_guide(kb, c.base_class, c.base_class))
        if c.level < 15:
            picks.append("guide/beginners-guide-first-steps-in-maple-world")
        picks.append("guide/best-grind-maps-every-level")
        if 21 <= c.level <= 30:
            picks.append("guide/kerning-city-party-quest-kpq-guide")
        picks.append("guide/exp-table-level-1-to-100")
        if c.level >= 60:
            picks.append("guide/forgotten-hollow-the-new-endgame-area")
    else:
        picks += ["guide/beginners-guide-first-steps-in-maple-world", "guide/best-grind-maps-every-level"]
    seen = []
    for k in picks:
        if k and kb.get(k) and k not in seen:
            seen.append(k)
    return seen


def summary_path(key: str, lang: str, page: str):
    digest = hashlib.sha1(page.encode("utf-8")).hexdigest()[:10]   # a KB update makes a new summary
    return SUMMARIES / f"{key.split('/', 1)[1]}-{lang}-{digest}.md"
