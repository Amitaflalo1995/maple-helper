"""The chat window's layout and state fixes (offscreen Qt): tags, pins, open/close, captures, scrolling."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QRect  # noqa: E402

from maplehelper.brain import META, streamed_text  # noqa: E402
from maplehelper.i18n import STRINGS, I18n  # noqa: E402


# ------------------------------------------------------------------ pure helpers

def test_streaming_never_shows_a_half_arrived_marker():
    assert streamed_text("Mano drops a shell.\n@@ME") == "Mano drops a shell."
    assert streamed_text("Mano drops a shell.\n@") == "Mano drops a shell."
    assert streamed_text(f"Mano drops a shell.\n{META}\n{{\"entities\"") == "Mano drops a shell."
    assert streamed_text("email me @ home") == "email me @ home"


def test_singular_forms():
    he, en = I18n("he"), I18n("en")
    assert he("history_count", n=1) == "תוצאה אחת" and en("history_count", n=1) == "1 result"
    assert en("history_count", n=3) == "3 results"
    assert "1" not in he("tip_job_soon", n=1, jobs="Hermit") and en("sess_questions", n=1) == "1 question"


@pytest.mark.parametrize("key", sorted(k for k in STRINGS if k.endswith("_one")))
def test_singular_variants_have_a_base_string(key):
    assert key[:-4] in STRINGS


def test_stat_changes_in_words():
    from maplehelper.ui.overlay import stats_text
    assert stats_text(I18n("en"), "acc 55, dmg_min 30, dmg_max 80") == \
        "Accuracy (ACC) 55, Min damage 30, Max damage 80"
    assert "dmg_min" not in stats_text(I18n("he"), "dmg_min 30")


def test_saved_spot_is_moved_onto_a_screen():
    from maplehelper.ui.overlay import visible_rect
    screens = [QRect(0, 0, 1920, 1080)]
    assert visible_rect(QRect(-20000, 50, 72, 72), screens) is None          # that monitor is gone
    assert visible_rect(QRect(1900, 1070, 72, 72), screens) == QRect(1848, 1008, 72, 72)
    assert visible_rect(QRect(100, 100, 72, 72), screens) == QRect(100, 100, 72, 72)


def test_card_subtitle_says_the_category_once():
    from maplehelper.ui.widgets import card_subtitle
    assert card_subtitle(I18n("he"), "monster", "Monster") == "מפלצת"
    assert card_subtitle(I18n("en"), "item", "Etc / Monster Drop") == "Item · Etc / Monster Drop"
    assert card_subtitle(I18n("he"), "crafting", None) == "קראפטינג"


# ------------------------------------------------------------------ the window

@pytest.fixture
def overlay(isolated_store, kb, monkeypatch):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from maplehelper import osapi
    from maplehelper.ui.overlay import Overlay
    for name in ("float_over_fullscreen", "activate_self", "focus_window"):
        monkeypatch.setattr(osapi, name, lambda *a: None)
    monkeypatch.setattr(osapi, "find_game_window", lambda: None)
    from maplehelper.ui import terms
    monkeypatch.setattr(terms, "LANG", terms.LANG)       # the chat's language must not leak into other tests
    s, p = isolated_store.Settings(), isolated_store.Profiles()
    c = p.add("Elipaz", "Thief", "Assassin", 32)
    p.set_active(c.id)
    ov = Overlay(s, p, kb, None)
    ov.setGeometry(QRect(-3000, -3000, 460, 640))
    ov.show()
    ov.app = app
    yield ov
    ov.hide()
    ov.bubble.hide()
    ov.deleteLater()


def pump(app, ms):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def test_tagging_cards_does_not_widen_the_window(overlay):
    w = overlay.width()
    overlay.set_tags(["monster/100100", "monster/100101", "monster/130101", "map/100000000", "npc/1012100"])
    pump(overlay.app, 100)
    assert overlay.minimumSizeHint().width() <= w and overlay.width() == w


def test_quick_open_close_keeps_the_window_size(overlay):
    overlay.save_geometry()                 # a remembered window, so opening doesn't place a default one
    overlay.hide()
    start = overlay.geometry()
    for _ in range(3):
        overlay.open_overlay(None, None)
        pump(overlay.app, 50)              # closed again mid-animation (F9 double-tap)
        overlay.close_overlay()
        pump(overlay.app, 300)
    assert overlay.geometry().size() == start.size()
    assert (overlay.settings["window"]["w"], overlay.settings["window"]["h"]) == (start.width(), start.height())


def test_a_failing_screenshot_brings_the_chat_back(overlay, monkeypatch):
    def boom(_hwnd):
        raise RuntimeError("capture failed")
    from maplehelper import osapi
    monkeypatch.setattr(osapi, "find_game_window", lambda: 1234)
    overlay.shot_provider = boom
    overlay.setWindowOpacity(0.0)
    overlay._fresh_shot()
    assert overlay.windowOpacity() == 1.0
    assert overlay._safe_shot(1234) is None


def test_what_now_while_busy_says_so_without_hiding_the_chat(overlay):
    overlay.busy = True
    before = overlay.feed_lay.count()
    overlay.what_now()
    overlay.what_now()
    assert overlay.windowOpacity() == 1.0
    assert overlay.feed_lay.count() - before == 1         # one notice, not one per click


def test_screenshot_hint_names_the_players_hotkey(overlay):
    overlay.settings["hotkey_toggle"] = "F8"
    overlay.game_hwnd, overlay.shot = None, None
    overlay._update_shot_hint()
    assert "F8" in overlay.shot_hint.text() and "F9" not in overlay.shot_hint.text()


def test_language_switch_updates_tooltips_and_term_language(overlay):
    from maplehelper.ui import terms
    overlay.settings["language"] = "en"
    overlay.apply_language()
    assert overlay.tools_btn.toolTip() == "Play tools" and overlay.clear_tags_btn.toolTip() == "Clear all tags"
    assert terms.LANG == "en"


def test_another_character_in_game_is_offered_not_overwritten(overlay):
    """A new character in game while the app's active one is another: nothing changes until the player adds it."""
    from maplehelper.brain import Answer
    from maplehelper.ui.widgets import NoticeCard
    before = overlay.profiles.active
    ans = Answer(text="ok", profile_update={"name": "NewGuy99", "level": 3, "job": "Beginner"})
    assert overlay._offer_other_character(ans, None, None)
    assert overlay.profiles.active is before and before.name == "Elipaz" and before.level == 32
    notices = overlay.findChildren(NoticeCard)
    assert notices
    notices[-1].clicked.emit()
    notices[-1].clicked.emit()                       # a double click adds it once
    new = overlay.profiles.active
    assert new.name == "NewGuy99" and new.level == 3 and len(overlay.profiles.characters) == 2
    # back on the first one, the same read offers to switch instead of adding again
    overlay.switch_character(before.id)
    assert overlay._offer_other_character(ans, None, None)
    overlay.findChildren(NoticeCard)[-1].clicked.emit()
    assert overlay.profiles.active.name == "NewGuy99" and len(overlay.profiles.characters) == 2
    # the same character (a name cut short at setup) is no offer
    assert not overlay._offer_other_character(Answer(text="ok", profile_update={"name": "NewGuy99x"}), None, None)
