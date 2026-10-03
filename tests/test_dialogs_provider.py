"""Choosing Claude or Codex in onboarding and settings (offscreen Qt, no real CLI calls)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def env(qapp, isolated_store, kb, monkeypatch):
    from maplehelper import providers
    # every account check answers instantly: Claude signed in, Codex installed but signed out
    monkeypatch.setattr(type(providers.get("claude")), "account", lambda self: {"status": "ok", "email": "a@b.c"})
    monkeypatch.setattr(type(providers.get("codex")), "account",
                        lambda self: {"status": "logged_out", "email": None, "method": None})
    s = isolated_store.Settings()
    s["language"] = "en"
    return s, isolated_store.Profiles(), kb


def test_onboarding_relabels_the_connect_page_for_codex(env):
    from maplehelper.ui.dialogs import Onboarding
    s, profiles, kb = env
    dlg = Onboarding(s, profiles, kb, lambda *_: "")
    assert dlg.install_btn.text() == "Install Claude Code"
    dlg._on_provider("codex")
    assert s["provider"] == "codex"
    assert dlg.install_btn.text() == "Install ChatGPT"
    assert dlg.login_btn.text() == "Sign in with ChatGPT"
    assert "OpenAI" in dlg.key_edit.placeholderText()
    assert "OpenAI" in dlg.privacy_label.text()


def test_onboarding_relabels_the_connect_page_for_gemini(env, monkeypatch):
    from maplehelper import providers
    from maplehelper.ui.dialogs import Onboarding
    monkeypatch.setattr(type(providers.get("gemini")), "account", lambda self: {"status": "not_installed", "email": None})
    s, profiles, kb = env
    dlg = Onboarding(s, profiles, kb, lambda *_: "")
    dlg._on_provider("gemini")
    assert s["provider"] == "gemini"
    assert dlg.install_btn.text() == "Install Gemini"
    assert dlg.login_btn.text() == "Sign in with Google"
    assert "AIza" in dlg.key_edit.placeholderText()
    assert "Google (Gemini)" in dlg.privacy_label.text()


def test_onboarding_ignores_a_late_status_for_the_other_provider(env):
    from maplehelper.ui.dialogs import Onboarding
    s, profiles, kb = env
    dlg = Onboarding(s, profiles, kb, lambda *_: "")
    dlg._on_provider("codex")
    dlg._on_status("claude", "ok")         # the check started before the switch
    assert not dlg._ai_ok
    dlg._on_status("codex", "ok")
    assert dlg._ai_ok


def test_settings_account_text_follows_the_provider(env):
    from maplehelper.ui.dialogs import SettingsDialog
    s, profiles, kb = env
    s["provider"] = "codex"
    dlg = SettingsDialog(s, profiles, kb, lambda *_: "")
    dlg._on_account({"status": "ok", "email": "a@b.c", "provider": "claude"})   # stale: ignored
    assert "a@b.c" not in dlg.account_label.text()
    dlg._on_account({"status": "ok", "email": None, "method": "chatgpt", "provider": "codex"})
    assert dlg.account_label.text() == "Signed in with ChatGPT"


def test_settings_switching_provider_tells_the_app(env):
    from maplehelper.ui.dialogs import SettingsDialog
    s, profiles, kb = env
    dlg = SettingsDialog(s, profiles, kb, lambda *_: "")
    seen = []
    dlg.account_changed.connect(lambda: seen.append(s["provider"]))
    dlg._on_provider("codex")
    assert seen == ["codex"]


def test_settings_model_pick_applies_right_away(env):
    from maplehelper.ui.dialogs import SettingsDialog
    s, profiles, kb = env
    s["provider"] = "claude"
    s["last_model"] = {"claude": "claude-sonnet-5"}
    dlg = SettingsDialog(s, profiles, kb, lambda *_: "")
    seen = []
    dlg.account_changed.connect(lambda: seen.append(s["model"]))
    assert dlg.model_pick.text() == "Sonnet (recommended)" and "Sonnet 5" in dlg.model_hint.text()
    dlg._on_model(dlg._model_values.index("opus"))
    assert s["model"] == "opus" and seen == ["opus"]


def test_onboarding_sign_in_lets_the_login_window_show_and_offers_reinstall(env, monkeypatch):
    from PySide6.QtCore import Qt
    from maplehelper import providers
    from maplehelper.ui.dialogs import Onboarding
    s, profiles, kb = env
    dlg = Onboarding(s, profiles, kb, lambda *_: "")
    dlg._on_provider("codex")
    monkeypatch.setattr(type(providers.get("codex")), "login", lambda self: object())
    dlg._start_login()
    assert not dlg.windowFlags() & Qt.WindowStaysOnTopHint      # the browser opens over it
    assert not dlg.login_hint.isHidden() and "ChatGPT" in dlg.login_hint.text()
    assert not dlg.install_btn.isHidden()
    dlg._on_status("codex", "ok")
    assert dlg.windowFlags() & Qt.WindowStaysOnTopHint          # back on top, connected
    assert dlg.login_hint.isHidden() and dlg.install_btn.isHidden()
    dlg.close()


def test_onboarding_sign_in_that_cannot_start_says_so(env, monkeypatch):
    from maplehelper import providers
    from maplehelper.ui.dialogs import Onboarding
    s, profiles, kb = env
    dlg = Onboarding(s, profiles, kb, lambda *_: "")
    dlg._on_provider("codex")
    monkeypatch.setattr(type(providers.get("codex")), "login", lambda self: None)
    dlg._start_login()
    assert "The ChatGPT sign-in didn't work" in dlg.login_hint.text()
    assert not dlg.install_btn.isHidden()
    dlg.close()


def test_onboarding_reports_a_sign_in_that_ended_in_failure(env, monkeypatch):
    from maplehelper import providers
    from maplehelper.ui.dialogs import Onboarding
    s, profiles, kb = env
    dlg = Onboarding(s, profiles, kb, lambda *_: "")
    dlg._on_provider("codex")

    class Ended:
        returncode = 1

        def poll(self):
            return 1
    monkeypatch.setattr(type(providers.get("codex")), "login", lambda self: Ended())
    dlg._start_login()
    dlg._poll_tick()
    assert "The ChatGPT sign-in didn't work" in dlg.login_hint.text()
    assert not dlg.install_btn.isHidden()
    dlg.close()


def _wait(qapp, done, seconds=5.0):
    import time
    end = time.time() + seconds
    while not done() and time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)


def test_onboarding_enter_moves_on_and_esc_does_not_quit(env, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from maplehelper.ui.dialogs import Onboarding
    s, profiles, kb = env
    dlg = Onboarding(s, profiles, kb, lambda *_: "")
    page = dlg.pages.index(dlg.form.parentWidget())
    dlg.stack.setCurrentIndex(page)
    dlg._update_nav()
    assert dlg.enter_button is dlg.next and not dlg.back.autoDefault()
    QTest.keyClicks(dlg.form.name, "Bob")
    QTest.keyClick(dlg.form.name, Qt.Key_Return)          # no class yet: stays, and never goes Back
    assert dlg.stack.currentIndex() == page
    dlg.form.class_group.buttons()[1].setChecked(True)     # Warrior, Lv. 10: one possible job
    QTest.keyClick(dlg.form.name, Qt.Key_Return)
    assert dlg.stack.currentIndex() == page + 1
    closed = []
    dlg.rejected.connect(lambda: closed.append(True))
    QTest.keyClick(dlg, Qt.Key_Escape)
    assert not closed                                      # Esc would have quit the app
    dlg.close()


def test_adding_a_character_can_still_be_cancelled_with_esc(env):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from maplehelper.ui.dialogs import Onboarding
    s, profiles, kb = env
    dlg = Onboarding(s, profiles, kb, lambda *_: "", only_character=True)
    closed = []
    dlg.rejected.connect(lambda: closed.append(True))
    QTest.keyClick(dlg, Qt.Key_Escape)
    assert closed


def test_onboarding_enter_in_the_key_field_checks_the_key_off_the_gui_thread(env, qapp, monkeypatch):
    import threading
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from maplehelper import providers
    from maplehelper.ui.dialogs import Onboarding
    s, profiles, kb = env
    seen = []
    monkeypatch.setattr(type(providers.get("claude")), "test_api_key",
                        lambda self, k: seen.append((k, threading.current_thread() is threading.main_thread())))
    dlg = Onboarding(s, profiles, kb, lambda *_: "")
    dlg.stack.setCurrentIndex(1)
    QTest.keyClicks(dlg.key_edit, "sk-ant-x")
    QTest.keyClick(dlg.key_edit, Qt.Key_Return)
    _wait(qapp, lambda: dlg.key_btn.isEnabled())
    assert seen == [("sk-ant-x", False)] and dlg.stack.currentIndex() == 1
    assert "didn't work" in dlg.key_hint.text() and not dlg._ai_ok
    dlg.key_edit.setText("sk-ключ")                          # used to raise inside the request, only logged
    dlg._check_key()
    assert "characters that don't belong" in dlg.key_hint.text() and len(seen) == 1
    dlg.close()


def test_onboarding_sign_in_that_times_out_says_try_again(env, monkeypatch):
    from PySide6.QtCore import Qt
    from maplehelper import providers
    from maplehelper.ui.dialogs import Onboarding
    s, profiles, kb = env
    dlg = Onboarding(s, profiles, kb, lambda *_: "")
    dlg._on_provider("codex")
    monkeypatch.setattr(type(providers.get("codex")), "login", lambda self: object())
    dlg._start_login()
    dlg._poll_left = 1
    dlg._poll_tick()
    assert not dlg._poll_timer.isActive() and not dlg._signing_in
    assert dlg.windowFlags() & Qt.WindowStaysOnTopHint
    assert "try again" in dlg.login_hint.text() and "by itself" not in dlg.login_hint.text()
    dlg.close()


def test_job_is_not_guessed_when_there_is_a_choice(env):
    from maplehelper.ui.dialogs import Onboarding
    s, profiles, kb = env
    form = Onboarding(s, profiles, kb, lambda *_: "", only_character=True).form
    form.name.setText("Bob")
    form.class_group.buttons()[1].setChecked(True)         # Warrior
    form.level.setValue(35)                                # Warrior, Fighter, Page, Spearman
    assert form.current_job() == "" and not form.valid()
    form.job.setCurrentText("Page")
    assert form.current_job() == "Page" and form.valid()


def test_settings_offers_install_and_says_when_a_sign_in_timed_out(env, monkeypatch):
    from maplehelper import providers
    from maplehelper.ui.dialogs import SettingsDialog
    s, profiles, kb = env
    s["provider"] = "codex"
    dlg = SettingsDialog(s, profiles, kb, lambda *_: "")
    dlg._on_account({"status": "not_installed", "email": None, "provider": "codex"})
    assert not dlg.install_btn.isHidden() and dlg.install_btn.text() == "Install ChatGPT"
    dlg._on_account({"status": "logged_out", "email": None, "provider": "codex"})
    assert dlg.install_btn.isHidden()

    class Waiting:                        # the sign-in still waits for the browser
        returncode = None

        def poll(self):
            return None
    monkeypatch.setattr(type(providers.get("codex")), "login", lambda self: Waiting())
    dlg._start_login()
    dlg._login_left = 1
    dlg._login_tick()
    assert not dlg._login_timer.isActive() and "try again" in dlg.account_hint.text()
    assert not dlg.account_hint.isHidden()
    dlg.close()


def test_settings_esc_keeps_unsaved_changes_and_keys_must_differ(env):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from maplehelper.ui.dialogs import SettingsDialog
    s, profiles, kb = env
    dlg = SettingsDialog(s, profiles, kb, lambda *_: "")
    closed = []
    dlg.rejected.connect(lambda: closed.append(True))
    QTest.keyClick(dlg, Qt.Key_Escape)
    assert not closed
    dlg.hk_voice.setCurrentText(dlg.hk_toggle.currentText())
    assert not dlg.save_btn.isEnabled() and not dlg.keys_error.isHidden()
    dlg._save()
    assert s["hotkey_voice"] != s["hotkey_toggle"]           # not saved like that
    dlg.hk_voice.setCurrentText("F12")
    assert dlg.save_btn.isEnabled() and dlg.keys_error.isHidden()
    dlg.close()


def test_tall_windows_fit_the_screen(env):
    from PySide6.QtGui import QGuiApplication
    from maplehelper.ui.dialogs import Onboarding, SettingsDialog
    s, profiles, kb = env
    avail = QGuiApplication.primaryScreen().availableGeometry().height()
    for dlg in (SettingsDialog(s, profiles, kb, lambda *_: ""), Onboarding(s, profiles, kb, lambda *_: "")):
        assert dlg.height() <= max(320, avail - 48)
        dlg.close()
