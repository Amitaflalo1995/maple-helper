"""The KB's guides as a small library: categories, "for you" picks, and a clean reading view.

The scraped pages carry the source site's menus and ads around the article; `parse` keeps the
article (title, intro, pros/cons, sections, tables) so the reader shows only the guide.
"""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field

from .store import DATA_DIR

SUMMARIES = DATA_DIR / "guide_summaries"
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


def _table_html(rows: list[list[str]]) -> str:
    esc = html.escape
    head, *body = rows
    return ("<table cellspacing='0' cellpadding='4'><tr>" + "".join(f"<th>{esc(c)}</th>" for c in head) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in body) + "</table>")


def to_html(g: Guide, labels: dict) -> str:
    """Readable HTML for QTextBrowser: headings, paragraphs, and real tables for "a | b | c" rows."""
    esc = html.escape
    out = []
    if g.pros or g.cons:
        for name, items in ((labels["pros"], g.pros), (labels["cons"], g.cons)):
            if items:
                out.append(f"<h3>{esc(name)}</h3><ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>")
    for heading, lines in g.sections:
        if heading:
            out.append(f"<h3>{esc(heading)}</h3>")
        table: list[list[str]] = []
        for ln in lines:
            if " | " in ln:
                table.append([c.strip() for c in ln.split(" | ")])
                continue
            if table:
                out.append(_table_html(table))
                table = []
            out.append(f"<p>{esc(ln)}</p>")
        if table:
            out.append(_table_html(table))
    return "\n".join(out)


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
