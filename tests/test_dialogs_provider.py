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
