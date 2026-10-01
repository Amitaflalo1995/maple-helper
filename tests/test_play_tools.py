"""Play tools: combat math (checked against NiaMeowDB's own numbers), quests, build tables, timers, EXP meter."""
import time
from pathlib import Path

import pytest

from maplehelper import buildplan, combat, plan, quests, timers

REAL_KB = Path(__file__).resolve().parent.parent / "data" / "kb"
needs_kb = pytest.mark.skipif(not (REAL_KB / "index.json").exists(), reason="no real knowledge base")


def test_accuracy_to_never_miss_matches_the_site():
    # Zombie Mushroom (Lv 24, Avoid 14): the monster page lists 47 / 56 / 65 ACC at levels 24 / 19 / 14
    assert [combat.acc_needed(lv, 24, 14) for lv in (24, 19, 14)] == [47, 56, 65]
    assert combat.hit_chance(47, 24, 24, 14) == 1.0 and combat.hit_chance(30, 24, 24, 14) < 0.5


def test_base_accuracy_and_damage():
    assert combat.base_acc("Warrior", 30, dex=30, luk=4) == 49
    assert combat.acc_per_point("Warrior") == pytest.approx(0.48)
    m = combat.Monster("monster/1", "Test", level=30, hp=1000, exp=50, pdef=0)
    assert combat.hits_to_kill(100, 300, m, 30) == (10, 5.0)
    assert combat.level_scale(30, 35) < 1 and combat.level_scale(30, 25) == 1


@needs_kb
def test_training_spots_are_reachable_and_ranked():
    from maplehelper.kb import KnowledgeBase
    kb = KnowledgeBase(REAL_KB)
    rows = combat.spots(kb, 30, acc=73, dmg=(140, 300), n=6)
    assert rows and all(combat.grind_map(s.map) for s in rows)
    assert not any("Orbis" in s.map or "Warrior's" in s.map for s in rows)
    assert rows == sorted(rows, key=lambda s: -s.score)


def test_timer_clock_and_parse():
    assert timers.clock(125) == "2:05" and timers.clock(3725) == "1:02:05"
    assert timers.parse_clock("3") == 180 and timers.parse_clock("2:30") == 150 and timers.parse_clock("x") is None


def test_timers_finish_once():
    import sys
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.instance() or QCoreApplication(sys.argv)
    tm = timers.Timers()
    done = []
    tm.finished.connect(done.append)
    r = tm.start("Haste", 200)
    r.ends = time.time() - 1
    tm._on_tick()
    tm._on_tick()
    assert done == ["Haste"] and tm.running[0].ends == 0
    tm.restart(r.id)
    assert tm.running[0].left() > 190
    tm.stop(tm.running[0].id)
    assert tm.running == []


@needs_kb
def test_exp_rate_across_a_level_up():
    from maplehelper.kb import KnowledgeBase
    kb = KnowledgeBase(REAL_KB)
    same = plan.exp_rate(kb, (0, 30, 40.0), (1800, 30, 55.0))
    assert same["pct_hour"] == 30.0 and same["minutes"] == 30.0
    up = plan.exp_rate(kb, (0, 30, 90.0), (1800, 31, 5.0))
    assert up and up["per_hour"] > 0
    assert plan.exp_rate(kb, (0, 30, 50.0), (60, 30, 50.0)) is None


@needs_kb
def test_quests_for_a_level():
    from maplehelper.kb import KnowledgeBase
    kb = KnowledgeBase(REAL_KB)
    r = quests.for_level(kb, 22, "Warrior", "Warrior", [])
    assert r["now"] and all(q.level <= 22 for q in r["now"]) and all(q.area != "Citizenship" for q in r["now"])
    assert r["now"] == sorted(r["now"], key=lambda q: (-q.exp, q.level))
    first = r["now"][0].key
    assert first not in [q.key for q in quests.for_level(kb, 22, "Warrior", "Warrior", [first])["now"]]
    mai = next(quests.quest(kb, k) for k, e in kb.entities.items() if e["name"] == "Mai's Training")
    assert mai.level == 3 and "Beginner" in mai.job and any("Blue Snail x 10" in n for n in mai.needs)


@needs_kb
def test_build_tables_follow_the_level():
    from maplehelper.kb import KnowledgeBase
    kb = KnowledgeBase(REAL_KB)
    key, tables = buildplan.tables(kb, "Warrior", "Warrior", 22, "en")
    assert key == "guide/warrior-class-guide"
    kinds = [t.kind for t in tables]
    assert "ap" in kinds and "sp" in kinds
    ap = next(t for t in tables if t.kind == "ap")
    assert "10-30" in ap.heading and ap.current is not None
    assert buildplan.current_row([["Level"], ["10"], ["11-12"], ["20"]], 15) == 2


def test_stats_from_a_screenshot_read(tmp_path, monkeypatch):
    from maplehelper import store
    monkeypatch.setattr(store.Profiles, "path", tmp_path / "profiles.json")
    p = store.Profiles()
    p.add("Kiwi", "Warrior", "Fighter", 34)
    changed = p.apply_update({"stats": {"acc": 78, "dmg_min": 340, "dmg_max": 160, "bogus": 5, "hp": -3}})
    assert p.active.stats == {"acc": 78, "dmg_min": 160, "dmg_max": 340}      # min/max swapped back, junk dropped
    assert changed and changed[0][0] == "stats"
    assert p.apply_update({"stats": {"acc": 78}}) == []                         # nothing new


@needs_kb
def test_tools_window_builds_every_page(tmp_path, monkeypatch):
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from maplehelper import store
    from maplehelper.kb import KnowledgeBase
    from maplehelper.ui.tools import PAGES, ToolsDialog
    monkeypatch.setattr(store.Profiles, "path", tmp_path / "profiles.json")
    monkeypatch.setattr(store.Settings, "path", tmp_path / "settings.json")
    p = store.Profiles()
    c = p.add("Kiwi", "Thief", "Assassin", 34)
    c.stats = {"acc": 80, "dmg_min": 150, "dmg_max": 320}
    s = store.Settings()
    tm = timers.Timers()
    d = ToolsDialog(KnowledgeBase(REAL_KB), p, s, "he", "", tm, {})
    for i in range(len(PAGES)):
        d.show_page(i)
        app.processEvents()
    d.calc_input.setText("Zombie Mushroom")
    d._fill_calc()
    d.t_name.setText("Haste")
    d.t_time.setText("3:20")
    d._add_timer()
    assert tm.running and tm.running[0].name == "Haste" and s["timer_presets"][-1] == {"name": "Haste", "seconds": 200}
    d._quest_done(quests.for_level(d.kb, 34, "Thief", "Assassin", [])["now"][0].key)
    assert len(c.quests_done) == 1
    d.close()
