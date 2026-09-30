"""Knowledge-base lookup against the fixture KB."""


def test_loads_index_and_aliases(kb):
    assert len(kb.entities) == 15
    assert kb.get("map/100000000")["name"] == "Henesys"


def test_longest_name_wins(kb):
    # "Red Snail" must not also report "Snail"
    assert kb.find_mentions("where do I find Red Snail?") == ["monster/130101"]
    assert kb.find_mentions("snails and a snail") == ["monster/100100"]


def test_multiple_mentions_in_order_of_length(kb):
    found = kb.find_mentions("Red Potion from a Blue Snail in Henesys")
    assert set(found) == {"item/2000000", "monster/100101", "map/100000000"}


def test_hebrew_alias_and_prefix(kb):
    assert kb.find_mentions("איפה רד סנייל?") == ["monster/130101"]
    assert kb.find_mentions("מה יש בהנסיס") == ["map/100000000"]      # ב + הנסיס


def test_resolve_names_after_speech_to_text(kb):
    assert kb.resolve_names("איפה חילזון אדום ליד הנסיס") == "איפה Red Snail ליד Henesys"
    # a glued Hebrew prefix is kept and hyphenated: "בהנסיס" -> "ב-Henesys"
    assert kb.resolve_names("מה יש בהנסיס") == "מה יש ב-Henesys"
    assert kb.resolve_names("ורד סנייל") == "ו-Red Snail"
    # but an alias inside a longer Hebrew word is left alone
    assert kb.resolve_names("אבגדהנסיסים") == "אבגדהנסיסים"


def test_page_body_strips_front_matter(kb):
    body = kb.page_body("monster/130101")
    assert body.startswith("# Red Snail") and "---" not in body[:5]
    assert kb.page("monster/0") == ""


def test_image_path(kb):
    assert kb.image_path("monster/130101").name == "130101.png"
    assert kb.image_path("monster/100100") is None           # listed but file missing
    assert kb.image_path("item/2000000") is None


def test_level_digest(kb):
    d = kb.level_digest(5)
    assert "Red Snail | 4 | 45 | 8 | Henesys Hunting Ground I, Snail Garden, Henesys Hunting Ground II" in d
    assert "Axe Stump" not in d                              # level 17 is outside 5-5..5+8
    assert kb.level_digest(200) == ""


def test_missing_kb_is_empty(tmp_path):
    from maplehelper.kb import KnowledgeBase
    empty = KnowledgeBase(tmp_path)
    assert empty.entities == {} and empty.find_mentions("Red Snail") == []
