"""Instant answers from the KB: only simple, unambiguous factual questions; the rest goes to Claude."""
import pytest

from maplehelper import quick
from maplehelper.i18n import I18n

t = I18n("en")


def first_monster(kb):
    return next(k for k, e in kb.entities.items() if e["category"] == "monster" and (e.get("props") or {}).get("HP"))


def test_stat_question_is_answered_from_the_kb(kb):
    key = first_monster(kb)
    e = kb.get(key)
    ans = quick.answer(f"how much HP does {e['name']} have?".replace("how ", "what's the "), kb, t)
    assert ans and f"HP: {e['props']['HP']}" in ans.text and ans.entities == [key]


def test_hebrew_stat_question(kb):
    key = first_monster(kb)
    e = kb.get(key)
    ans = quick.answer(f"כמה HP יש ל-{e['name']}?", kb, t)
    assert ans and str(e["props"]["HP"]) in ans.text


@pytest.mark.parametrize("q", [
    "how should I level my Assassin?",      # judgement
    "מה כדאי לעשות בלבל 30?",                 # judgement, nothing named
    "what is this monster?",                 # needs the screenshot
    "tell me everything about the game and all the monsters you know please",  # long
])
def test_everything_else_goes_to_claude(kb, q):
    assert quick.answer(q, kb, t) is None


def test_hebrew_words_match_whole_words_only():
    assert quick.WHO.search("מי מפיל את זה")
    assert not quick.WHO.search("מימון")


def test_a_name_containing_a_stat_word_is_not_a_stat_question():
    # "לבלו סנייל" (Blue Snail) contains "לבל" (level) but doesn't ask about the level
    level = next(rx for rx, key, _ in quick.STATS if key == "Level")
    assert not level.search("כמה HP יש לבלו סנייל?")
    assert level.search("באיזה לבל Mano?") and level.search("what level is Mano")
