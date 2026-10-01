"""The answer evals: the case file is always valid, and the instant answers pass against the real KB when it's here.

Claude mode is never run from tests: it spends a real player's plan usage.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import eval_answers

REAL_KB = eval_answers.KB
needs_real_kb = pytest.mark.skipif(not (REAL_KB / "index.json").exists(),
                                   reason="real knowledge base not present (data/kb)")


def ans(text="", entities=(), drop_groups=()):
    return SimpleNamespace(text=text, entities=list(entities), drop_groups=list(drop_groups))


def test_case_file_is_valid():
    cases = eval_answers.load_cases()
    assert eval_answers.validate_cases(cases) == []
    assert len(cases) >= 40
    he = sum(c["lang"] == "he" for c in cases)
    assert 0.5 <= he / len(cases) <= 0.75                # mostly Hebrew, like the players
    assert any(c["checks"].get("instant") is False for c in cases)


@pytest.mark.parametrize("case, problem", [
    ({"id": "Bad Id", "question": "q", "lang": "he", "kind": "stats", "checks": {"instant": False}}, "lowercase"),
    ({"id": "a", "question": " ", "lang": "he", "kind": "stats", "checks": {"instant": False}}, "empty question"),
    ({"id": "a", "question": "q", "lang": "fr", "kind": "stats", "checks": {"instant": False}}, "lang"),
    ({"id": "a", "question": "q", "lang": "he", "kind": "nope", "checks": {"instant": False}}, "kind"),
    ({"id": "a", "question": "q", "lang": "he", "kind": "stats", "checks": {"must_mentoin": ["x"]}}, "unknown checks"),
    ({"id": "a", "question": "q", "lang": "he", "kind": "stats", "checks": {"must_mention": "x"}}, "list of strings"),
    ({"id": "a", "question": "q", "lang": "he", "kind": "stats", "checks": {"instant": "yes"}}, "true or false"),
    ({"id": "a", "question": "q", "lang": "he", "kind": "stats", "checks": {"instant": True}}, "something to check"),
])
def test_validation_catches_typos(case, problem):
    assert any(problem in p for p in eval_answers.validate_cases([case]))


def test_duplicate_ids_are_rejected():
    c = {"id": "a", "question": "q", "lang": "he", "kind": "stats", "checks": {"instant": False}}
    assert any("duplicate" in p for p in eval_answers.validate_cases([c, dict(c)]))


def test_score_reads_text_and_card_names(kb):
    # an instant drops answer names the items only on its cards; numbers match with or without separators
    a = ans("Red Snail · HP: 7,420", entities=["monster/130101"],
            drop_groups=[{"monster": "monster/100101", "items": ["item/2000000"]}])
    checks = {"must_mention": ["7420", "red potion", "Blue Snail"], "must_not_mention": ["P.DMG"],
              "entities_include": ["monster/130101", "item/2000000"]}
    assert eval_answers.score(checks, a, kb) == []


def test_score_reports_every_problem(kb):
    a = ans("Snail drops P.DMG", entities=["monster/100100"])
    checks = {"must_mention": ["Red Potion"], "must_mention_any": ["Henesys", "Snail Garden"],
              "must_not_mention": ["p.dmg"], "entities_include": ["item/2000000"]}
    assert eval_answers.score(checks, a, kb) == [
        "missing 'Red Potion'", "none of 'Henesys', 'Snail Garden'", "mentions 'p.dmg'", "no card for item/2000000"]


def test_quick_mode_on_the_fixture_kb(kb):
    cases = [
        {"id": "hp", "question": "Red Snail hp", "lang": "en", "kind": "stats",
         "checks": {"must_mention": ["45"], "entities_include": ["monster/130101"], "instant": True}},
        {"id": "judge", "question": "should I hunt Red Snail?", "lang": "en", "kind": "judgement",
         "checks": {"instant": False}},
        {"id": "wrongly-claude", "question": "Red Snail hp", "lang": "en", "kind": "stats", "checks": {"instant": False}},
        {"id": "claude-only", "question": "where is Athena Pierce", "lang": "en", "kind": "npc",
         "checks": {"must_mention": ["Henesys"]}},
    ]
    results = {r["id"]: r for r in eval_answers.run_quick(cases, kb)}
    assert set(results) == {"hp", "judge", "wrongly-claude"}       # no "instant": not a quick-mode case
    assert results["hp"]["ok"] and results["judge"]["ok"]
    assert not results["wrongly-claude"]["ok"] and "answered instantly" in results["wrongly-claude"]["problems"][0]


def test_reports_compare_with_the_previous_one(tmp_path):
    old = [{"id": "a", "ok": True}, {"id": "b", "ok": False}, {"id": "c", "ok": True}]
    (tmp_path / "20261001-090000.json").write_text(json.dumps({"results": old}), encoding="utf-8")
    new = [{"id": "a", "lang": "he", "kind": "stats", "ok": False, "problems": ["missing 'x'"]},
           {"id": "b", "lang": "he", "kind": "stats", "ok": True, "problems": []},
           {"id": "d", "lang": "en", "kind": "guide", "ok": False, "problems": ["missing 'y'"]}]
    path = eval_answers.save_report(new, "sonnet", folder=tmp_path)
    prev = eval_answers.previous_report(tmp_path, before=path)
    assert eval_answers.compare(prev, new) == (["a"], ["b"])      # "d" is new: nothing to compare with
    assert eval_answers.compare(None, new) == ([], [])


def test_claude_mode_refuses_to_run_under_pytest(capsys):
    fixture_kb = Path(__file__).parent / "fixtures" / "kb"
    assert eval_answers.main(["--mode", "claude", "--yes", "--kb", str(fixture_kb)]) == 2
    assert "refusing" in capsys.readouterr().out


@pytest.fixture(scope="module")
def real_kb():
    from maplehelper.kb import KnowledgeBase
    return KnowledgeBase(REAL_KB)


@needs_real_kb
def test_case_keys_exist_in_the_real_kb(real_kb):
    missing = [(c["id"], k) for c in eval_answers.load_cases() for k in c["checks"].get("entities_include", [])
               if not real_kb.get(k)]
    assert missing == []


@needs_real_kb
def test_instant_answers_pass_on_the_real_kb(real_kb):
    results = eval_answers.run_quick(eval_answers.load_cases(), real_kb)
    failed = {r["id"]: r["problems"] for r in results if not r["ok"]}
    assert results and failed == {}


def test_claude_runner_scores_and_cleans_up(kb, monkeypatch):
    # a stand-in Brain: the real one would spend plan usage
    from maplehelper import brain
    from maplehelper.brain import Answer

    class FakeBrain:
        shut = False

        def __init__(self, kb, model):
            pass

        def available(self):
            return True

        def ask(self, question, character, history, screenshot_jpeg):
            if "fail" in question:
                return Answer(error="usage_limit")
            return Answer(text="Red Snail lives in Snail Garden", entities=["monster/130101"], cost_usd=0.01)

        def shutdown(self):
            FakeBrain.shut = True

    monkeypatch.setattr(brain, "Brain", FakeBrain)
    cases = [{"id": "ok", "question": "where is Red Snail", "lang": "en", "kind": "where",
              "checks": {"must_mention": ["Snail Garden"], "instant": True}},
             {"id": "err", "question": "fail", "lang": "en", "kind": "where", "checks": {"must_mention": ["x"]}}]
    results = eval_answers.run_claude(cases, kb)
    assert [r["ok"] for r in results] == [True, False]
    assert results[1]["problems"] == ["error: usage_limit"] and results[0]["cost_usd"] == 0.01
    assert FakeBrain.shut
