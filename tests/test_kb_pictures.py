"""Every entity a card can show has a picture, and drops are read with their item keys.

Runs against the downloaded knowledge base (data/kb); skipped where it isn't present (e.g. CI without data).
"""
import pytest

from maplehelper.kb import KnowledgeBase
from maplehelper.store import BUNDLED_KB

pytestmark = pytest.mark.skipif(not (BUNDLED_KB / "index.json").exists() or
                                len(KnowledgeBase(BUNDLED_KB).entities) < 1000,
                                reason="full knowledge base not downloaded")

CARD_CATEGORIES = ("monster", "item", "npc", "map", "quest", "skill", "class")


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase(BUNDLED_KB)


def test_every_card_has_a_picture(kb):
    missing = [k for k, e in kb.entities.items() if e["category"] in CARD_CATEGORIES and not kb.picture(k)]
    assert missing == []


def test_real_pictures_cover_almost_everything(kb):
    keys = [k for k, e in kb.entities.items() if e["category"] in CARD_CATEGORIES]
    real = sum(1 for k in keys if kb.image_path(k))
    assert real / len(keys) > 0.99


def test_quest_shows_its_npc(kb):
    q = next(k for k, e in kb.entities.items() if e["name"] == "Pio's Collecting Recycled Goods")
    assert kb.image_path(q) and "npc" in str(kb.image_path(q))


def test_blue_snail_drops_are_items_with_pictures(kb):
    drops = kb.monster_drops("monster/3")
    names = {kb.get(k)["name"] for k in drops}
    assert {"Blue Snail Shell", "Red Potion"} <= names
    assert all(kb.image_path(k) for k in drops)
