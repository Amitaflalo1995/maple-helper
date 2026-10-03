"""First-run UI: job names in the player's language (English kept), the hand cursor, the chat tour (offscreen Qt)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _form(lang, kb):
    from maplehelper.i18n import I18n
    from maplehelper.ui.dialogs import CharacterForm
    return CharacterForm(I18n(lang), kb)


def _pick(form, cls, level):
    form.level.setValue(level)
    next(b for b in form.class_group.buttons() if b.property("cls") == cls).setChecked(True)


def test_every_job_has_a_hebrew_name():
    from maplehelper.jobs import JOB_HE, JOBS
    for cls, jobs in JOBS.items():
        assert cls in JOB_HE
        for job, _ in jobs:
            assert job in JOB_HE, job


def test_hebrew_form_lists_hebrew_names_and_keeps_english(qapp, kb):
    form = _form("he", kb)
    _pick(form, "Warrior", 35)
    assert "פייטר · Fighter" in form.job._items
    form.job.setCurrentIndex(form.job._items.index("פייטר · Fighter"))
    form._job_picked = True                     # as a click on the list does
    assert form.current_job() == "Fighter"
    form.level.setValue(40)                     # the pick survives a level change
    assert form.current_job() == "Fighter"


def test_english_form_is_unchanged(qapp, kb):
    form = _form("en", kb)
    _pick(form, "Warrior", 35)
    assert "Fighter" in form.job._items
    assert all("·" not in item for item in form.job._items)


def test_load_selects_the_saved_job_in_hebrew(qapp, kb):
    from maplehelper.store import Character
    form = _form("he", kb)
    form.load(Character(id="x", name="Amit", base_class="Warrior", job="Page", level=35))
    assert form.job.currentText() == "פייג' · Page"
    assert form.current_job() == "Page"


def test_buttons_get_the_hand_cursor(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    from maplehelper.app import _HandCursor
    hand = _HandCursor(qapp)
    qapp.installEventFilter(hand)
    try:
        b = QPushButton("x")
        b.ensurePolished()
        assert b.cursor().shape() == Qt.PointingHandCursor
    finally:
        qapp.removeEventFilter(hand)


def test_tour_walks_every_visible_button_and_marks_itself_done(qapp, isolated_store, kb, monkeypatch):
    from maplehelper.ui import tour as tour_mod
    from maplehelper.ui.overlay import Overlay
    s = isolated_store.Settings()
    ov = Overlay(s, isolated_store.Profiles(), kb, None)
    ov.resize(520, 760)
    ov.show()
    ov.start_tour()
    tr = ov._tour
    assert tr is not None and tr.steps[0][1] == "tour_welcome"
    seen = []
    for _ in range(len(tr.steps)):
        assert tr.title.text() and tr.body.text() and "{" not in tr.body.text()
        seen.append(tr.steps[tr.i][1])
        tr.next_btn.click()
    assert seen[-1] == "tour_done" and "tour_tools" in seen
    assert s["tour_done"] is True and ov._tour is None
    assert set(k for _, k in tour_mod.STEPS) >= set(seen)


def test_last_session_card_continues_that_characters_chat(qapp, isolated_store, kb):
    from PySide6.QtWidgets import QPushButton

    from maplehelper.ui.overlay import Overlay
    from maplehelper.ui.widgets import SessionCard
    s, p = isolated_store.Settings(), isolated_store.Profiles()
    a = p.add("Main", "Thief", "Assassin", 31)
    b = p.add("Alt", "Beginner", "Beginner", 1)
    p.set_active(a.id)
    h = isolated_store.History(b.id)
    h.append("user", "where is Mano?")
    h.append("assistant", "In the Henesys hunting ground.")
    t = max(m["t"] for m in h.recent())
    s["last_session"] = {"minutes": 5, "from": t - 60, "to": t, "chars": [
        {"id": b.id, "name": "Alt", "start_level": 1, "end_level": 1, "start_job": "Beginner", "end_job": "Beginner",
         "questions": 1, "quests_done": [], "quests_started": []}]}
    ov = Overlay(s, p, kb, None)
    ov._show_last_session()
    card = ov.findChildren(SessionCard)[-1]
    go = next(x for x in card.findChildren(QPushButton) if x.objectName() == "Link")
    go.click()
    assert p.active_id == b.id and "where is Mano?" in ov._hidden_context
