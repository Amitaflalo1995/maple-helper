"""Guides library: the reader keeps only the article, guides sort into categories, picks fit the character."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from maplehelper import guides

PAGE = """---
{"name": "Assassin Guide", "category": "guide"}
---

# MapleStory Classic Assassin Guide: Lv 30-70

Assassin guide for levels 30-70.

Explore the database
Items Monsters Maps World Map Classes
Ad blocked? Fair. NiaMeowDB pays for catnip with ads.
Buy us a coffee →
Pros
Highest ranged damage.
Cons
Stars cost mesos.
Contents
Starting at level 30
Claws and stars
Starting at level 30
This guide continues from the Thief guide.
Claws and stars
Claw | Level | ATT
Steelguards | 30 | 15
"""


def test_parse_keeps_only_the_article():
    g = guides.parse("guide/assassin-class-guide", PAGE)
    assert g.title == "MapleStory Classic Assassin Guide: Lv 30-70"
    assert g.intro == "Assassin guide for levels 30-70."
    assert g.pros == ["Highest ranged damage."] and g.cons == ["Stars cost mesos."]
    assert [h for h, _ in g.sections] == ["Starting at level 30", "Claws and stars"]
    html = guides.to_html(g, {"pros": "Pros", "cons": "Cons"})
    assert "<table" in html and "<td>Steelguards</td>" in html
    assert "Explore the database" not in html and "catnip" not in html


@pytest.mark.parametrize("key,cat", [("guide/fighter-class-guide", "classes"),
                                     ("guide/best-grind-maps-every-level", "leveling"),
                                     ("guide/weapon-reach", "mechanics"),
                                     ("guide/maplestory-classic-glossary", "general")])
def test_categories(key, cat):
    assert guides.category(key) == cat


REAL_KB = Path(__file__).resolve().parent.parent / "data" / "kb"


@pytest.mark.skipif(not (REAL_KB / "index.json").exists(), reason="no real knowledge base")
def test_picks_for_a_character_start_with_their_job():
    from maplehelper.kb import KnowledgeBase
    kb = KnowledgeBase(REAL_KB)
    picks = guides.for_you(kb, SimpleNamespace(base_class="Thief", job="Assassin", level=34))
    assert picks[:2] == ["guide/assassin-class-guide", "guide/thief-class-guide"]
    assert "guide/best-grind-maps-every-level" in picks
    assert all(g.sections for g in (guides.parse(x["key"], kb.page(x["key"])) for x in guides.all_guides(kb)))
