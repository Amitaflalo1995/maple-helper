"""The 'last session' summary: what changed for each character while playing."""
from types import SimpleNamespace

from maplehelper import session
from maplehelper.i18n import I18n


def char(cid="a", name="Kiwi", level=30, job="Assassin"):
    return SimpleNamespace(id=cid, name=name, level=level, job=job)


def test_summary_tracks_levels_quests_and_questions():
    kiwi = char()
    s = session.SessionStats(now=0)
    s.touch(kiwi)
    s.question(kiwi, now=60)
    s.question(kiwi, now=40 * 60)
    s.change(kiwi, "quest+", "Mai's Training")
    s.change(kiwi, "quest-", "Mai's Training")
    kiwi.level = 33
    out = s.summary(SimpleNamespace(characters=[kiwi]))
    assert out["minutes"] == 40
    row = out["chars"][0]
    assert (row["start_level"], row["end_level"], row["questions"]) == (30, 33, 2)
    assert row["quests_done"] == ["Mai's Training"]
    text = "\n".join(session.lines(out, I18n("en")))
    assert "30 → 33" in text and "Mai's Training" in text and "2 questions" in text


def test_nothing_happened_means_no_summary():
    kiwi = char()
    s = session.SessionStats(now=0)
    s.touch(kiwi)
    assert s.summary(SimpleNamespace(characters=[kiwi])) is None


def test_deleted_character_is_left_out():
    s = session.SessionStats(now=0)
    s.question(char(cid="gone"))
    assert s.summary(SimpleNamespace(characters=[])) is None
