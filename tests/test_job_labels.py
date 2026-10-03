"""The character form shows job names in the player's language and keeps the English one (offscreen Qt)."""
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
