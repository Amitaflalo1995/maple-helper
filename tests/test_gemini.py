"""Gemini CLI provider: command, locked home, output parsing, sign-in files and discovery (no real CLI calls)."""
import io
import json
import os

import pytest

from maplehelper import providers
from maplehelper.providers import base, gemini


def events(*evs):
    return [json.dumps(e) + "\n" for e in evs]


RESULT = {"type": "result", "status": "success", "stats": {"models": {
    "gemini-3.8-flash": {"input_tokens": 50, "output_tokens": 0},       # the router
    "gemini-3.8-pro": {"input_tokens": 900, "output_tokens": 40}}}}


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "gemini-home"
    monkeypatch.setattr(gemini, "home", lambda: h)
    return h


def test_registered_with_its_own_settings():
    g = providers.get("gemini")
    assert g.name == "gemini" and g.label == "Gemini"
    assert g.model_setting == "gemini_model" and g.saver_model == "flash" and not g.reports_usage
    assert g.models()[0] == (None, "Auto") and ("pro", "Pro") in g.models()
    from maplehelper.store import DEFAULT_SETTINGS
    assert "gemini_model" in DEFAULT_SETTINGS and DEFAULT_SETTINGS["gemini_model"] is None


def test_command_is_read_only_and_takes_the_question_on_stdin():
    c = gemini.gemini_command(["node", "gemini.js"], "pro", "C:/shots")
    assert c[:2] == ["node", "gemini.js"]
    assert c[c.index("-p") + 1] == ""                                   # nothing added to the stdin question
    assert c[c.index("--approval-mode") + 1] == "plan" and c[c.index("-e") + 1] == "none"
    assert c[c.index("-o") + 1] == "stream-json" and "--skip-trust" in c
    assert c[c.index("--include-directories") + 1] == "C:/shots" and c[c.index("-m") + 1] == "pro"
    bare = gemini.gemini_command(["gemini"])
    assert "--include-directories" not in bare and "-m" not in bare


def test_home_settings_lock_everything_down(home):
    gemini.prepare_home(api_key=False)
    s = json.loads((home / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    assert s["tools"]["core"] == ["read_file", "grep_search", "glob"]
    assert s["mcp"]["allowed"] == [] and s["hooksConfig"]["enabled"] is False
    assert s["security"]["auth"]["selectedType"] == "oauth-personal"
    gemini.prepare_home(api_key=True)
    s = json.loads((home / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    assert s["security"]["auth"]["selectedType"] == "gemini-api-key"


def test_env_keeps_the_players_own_gemini_setup_out(home, monkeypatch):
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GEMINI_BASE_URL", "GEMINI_SYSTEM_MD", "NO_BROWSER"):
        monkeypatch.setenv(k, "leftover")
    e = gemini.env()
    assert not any(k in e for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GEMINI_BASE_URL",
                                    "GEMINI_SYSTEM_MD", "NO_BROWSER"))
    assert e["GEMINI_CLI_HOME"] == str(home) and e["GEMINI_CLI_NO_RELAUNCH"] == "true"
    e = gemini.env("AIzaKEY", "C:/sys.md")
    assert e["GEMINI_API_KEY"] == "AIzaKEY" and e["GEMINI_SYSTEM_MD"] == "C:/sys.md"


class TestEvents:
    def test_streams_and_keeps_only_the_text_after_the_last_tool(self):
        seen = []
        text, result, errors, session = gemini.parse_events(events(
            {"type": "init", "session_id": "7f725bdb-01c4", "model": "auto"},
            {"type": "message", "role": "user", "content": "where?"},
            {"type": "message", "role": "assistant", "content": "I'll check. ", "delta": True},
            {"type": "tool_use", "tool_name": "read_file", "parameters": {"file_path": "x.md"}},
            {"type": "tool_result", "status": "success"},
            {"type": "message", "role": "assistant", "content": "Hunt ", "delta": True},
            {"type": "message", "role": "assistant", "content": "snails.", "delta": True},
            RESULT), seen.append)
        assert text == "Hunt snails." and seen[-1] == "Hunt snails." and seen[0] == "I'll check. "
        assert session == "7f725bdb-01c4" and errors == []
        r = gemini.to_result(text, result, errors, "")
        assert r.error is None and r.text == "Hunt snails." and r.model == "gemini-3.8-pro"

    @pytest.mark.parametrize("message,kind", [
        ("API key not valid. Please pass a valid API key.", "not_logged_in"),
        ("Manual authorization is required but the current session is non-interactive.", "not_logged_in"),
        ("You have exhausted your capacity on this model. Quota exceeded", "usage_limit"),
        ("[API Error: got status: 429 Too Many Requests]", "usage_limit"),
        ("getaddrinfo ENOTFOUND generativelanguage.googleapis.com", "offline"),
    ])
    def test_errors(self, message, kind):
        _, result, errors, _ = gemini.parse_events(events(
            {"type": "result", "status": "error", "error": {"type": "Error", "message": message}}))
        assert gemini.to_result("", result, errors, "").error == kind

    def test_no_result_at_all(self):
        assert gemini.to_result("", None, [], "Please set an Auth method").error == "not_logged_in"
        assert gemini.to_result("", None, [], "").error == "no_result"


class TestAccount:
    def test_not_installed_without_the_cli_or_node(self, home, monkeypatch):
        monkeypatch.setattr(gemini, "find_gemini", lambda: None)
        assert providers.get("gemini").account()["status"] == "not_installed"
        monkeypatch.setattr(gemini, "find_gemini", lambda: "gemini.js")
        monkeypatch.setattr(gemini, "command", lambda exe: None)       # no Node.js
        assert providers.get("gemini").account()["status"] == "not_installed"

    def test_signed_in_shows_the_google_email_and_sign_out_forgets_it(self, home, monkeypatch):
        monkeypatch.setattr(gemini, "find_gemini", lambda: "gemini")
        monkeypatch.setattr(gemini, "command", lambda exe: [exe])
        g = providers.get("gemini")
        assert g.account() == {"status": "logged_out", "email": None}
        d = home / ".gemini"
        d.mkdir(parents=True)
        (d / "oauth_creds.json").write_text(json.dumps({"refresh_token": "r", "access_token": "a"}))
        (d / "google_accounts.json").write_text(json.dumps({"active": "p@gmail.com", "old": []}))
        assert g.account() == {"status": "ok", "email": "p@gmail.com"}
        assert g.logout()
        assert g.account()["status"] == "logged_out" and not (d / "oauth_creds.json").exists()

    def test_sign_in_answers_the_cli_and_runs_hidden_in_its_home(self, home, monkeypatch):
        seen = {}
        monkeypatch.setattr(gemini, "find_gemini", lambda: "gemini.js")
        monkeypatch.setattr(gemini, "command", lambda exe: ["node.exe", exe])
        monkeypatch.setattr(gemini, "open_login", lambda start, args, env, answer, cwd: seen.update(
            start=start, args=args, env=env, answer=answer, cwd=cwd) or "proc")
        assert providers.get("gemini").login() == "proc"
        assert seen["start"] == ["node.exe", "gemini.js"] and seen["answer"] == "y\n"
        assert seen["cwd"] == str(home) and seen["env"]["GEMINI_CLI_HOME"] == str(home)
        assert "GEMINI_API_KEY" not in seen["env"]
        s = json.loads((home / ".gemini" / "settings.json").read_text(encoding="utf-8"))
        assert s["security"]["auth"]["selectedType"] == "oauth-personal"


def test_open_login_types_the_answer(monkeypatch):
    class FakeProc:
        def __init__(self, cmd, **kw):
            self.cmd, self.kw, self.stdout = cmd, kw, iter([])
            self.stdin = io.BytesIO()
            self.stdin.close = lambda: None
            FakeProc.last = self

        def poll(self):
            return None

        def wait(self):
            return 0
    monkeypatch.setattr(base.subprocess, "Popen", FakeProc)
    base.open_login(["node.exe", "gemini.js"], ["-p", "hi"], answer="y\n", cwd="C:/h")
    p = FakeProc.last
    assert p.cmd == ["node.exe", "gemini.js", "-p", "hi"] and p.kw["cwd"] == "C:/h"
    assert p.kw["stdin"] == base.subprocess.PIPE and p.stdin.getvalue() == b"y\n"
    base._login = None


class TestDiscovery:
    def test_windows_runs_the_script_never_the_cmd_shim(self, tmp_path, monkeypatch):
        script = tmp_path / "npm" / gemini.PACKAGE
        script.parent.mkdir(parents=True)
        script.write_text("")
        monkeypatch.setenv("APPDATA", str(tmp_path))
        monkeypatch.setattr(gemini.shutil, "which", lambda _n: None)
        assert gemini.find_windows() == str(script)
        monkeypatch.setattr(gemini, "find_node", lambda: "C:/nodejs/node.exe")
        assert gemini.command(str(script), platform="win32") == ["C:/nodejs/node.exe", str(script)]
        monkeypatch.setattr(gemini, "find_node", lambda: None)
        assert gemini.command(str(script), platform="win32") is None
        assert gemini.command("/opt/homebrew/bin/gemini", platform="darwin") == ["/opt/homebrew/bin/gemini"]

    def test_an_npm_install_with_its_own_prefix(self, tmp_path, monkeypatch):
        script = tmp_path / "custom" / gemini.PACKAGE
        script.parent.mkdir(parents=True)
        script.write_text("")
        monkeypatch.setenv("APPDATA", str(tmp_path / "nothing"))
        monkeypatch.setattr(gemini.shutil, "which", lambda _n: str(tmp_path / "custom" / "gemini.cmd"))
        assert gemini.find_windows() == str(script)

    def test_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        monkeypatch.setattr(gemini.shutil, "which", lambda _n: None)
        assert gemini.find_windows() is None


class FakePopen:
    """Records the run and replays canned Gemini output; checks the files exist while it runs."""
    calls: list = []
    stdout_lines: list[str] = []

    def __init__(self, cmd, **kw):
        FakePopen.calls.append((cmd, kw))
        shots = cmd[cmd.index("--include-directories") + 1] if "--include-directories" in cmd else None
        self.shot = open(os.path.join(shots, "maplehelper-shot-0.jpg"), "rb").read() if shots else None
        self.system = open(kw["env"]["GEMINI_SYSTEM_MD"], encoding="utf-8").read()
        FakePopen.last = self
        self.stdin = io.BytesIO()
        self.stdin.close = lambda: None
        self.stdout = iter(line.encode() for line in FakePopen.stdout_lines)
        self.stderr = io.BytesIO(b"")
        self.returncode = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class TestBackend:
    @pytest.fixture
    def kb(self, kb_copy):
        from maplehelper.kb import KnowledgeBase
        return KnowledgeBase(kb_copy)

    def make(self, kb, home, monkeypatch, api_key=None):
        FakePopen.calls = []
        FakePopen.stdout_lines = events(
            {"type": "init", "session_id": "abcdef12-3456"},
            {"type": "message", "role": "assistant", "content": "Hunt **Red Snail**.\n@@META@@\n", "delta": True},
            {"type": "message", "role": "assistant", "content": '{"entities": ["monster/130101"]}', "delta": True},
            RESULT)
        monkeypatch.setattr(gemini.subprocess, "Popen", FakePopen)
        monkeypatch.setattr(gemini, "command", lambda exe, platform=None: ["gemini"])
        from maplehelper.brain import Brain
        b = Brain(kb, provider="gemini", api_key=api_key)
        b.backend.exe = "gemini"
        return b

    def test_answer_screenshot_and_instructions(self, kb, home, monkeypatch):
        chats = home / ".gemini" / "tmp" / "kb" / "chats"
        chats.mkdir(parents=True)
        (chats / "session-2026-10-03T08-21-abcdef12.jsonl").write_text("{}")
        (chats / "session-2026-10-03T08-21-other123.jsonl").write_text("{}")
        b = self.make(kb, home, monkeypatch)
        ans = b.ask("where is Red Snail?", None, None, b"JPEGDATA")
        assert ans.error is None and ans.text == "Hunt **Red Snail**."
        assert ans.entities[0] == "monster/130101"
        cmd, kw = FakePopen.calls[0]
        assert kw["cwd"] == str(kb.root) and kw["creationflags"] == base.CREATE_NO_WINDOW
        assert FakePopen.last.shot == b"JPEGDATA"
        question = FakePopen.last.stdin.getvalue().decode()
        assert "<question>" in question and question.rstrip().endswith("@maplehelper-shot-0.jpg")
        assert "read_file" in FakePopen.last.system                         # our instructions + the tools note
        # nothing left behind: the screenshot folder, the instructions file, this run's chat file
        assert not os.path.exists(cmd[cmd.index("--include-directories") + 1])
        assert not os.path.exists(kw["env"]["GEMINI_SYSTEM_MD"])
        assert [f.name for f in chats.iterdir()] == ["session-2026-10-03T08-21-other123.jsonl"]

    def test_account_login_vs_api_key(self, kb, home, monkeypatch):
        b = self.make(kb, home, monkeypatch)
        b.ask("hi", None, None, None)
        cmd, kw = FakePopen.calls[0]
        assert "GEMINI_API_KEY" not in kw["env"] and "--include-directories" not in cmd
        b = self.make(kb, home, monkeypatch, api_key="AIzaKEY")
        b.ask("hi", None, None, None)
        assert FakePopen.calls[0][1]["env"]["GEMINI_API_KEY"] == "AIzaKEY"
        s = json.loads((home / ".gemini" / "settings.json").read_text(encoding="utf-8"))
        assert s["security"]["auth"]["selectedType"] == "gemini-api-key"

    def test_summary_on_flash_in_an_empty_folder(self, kb, home, monkeypatch):
        b = self.make(kb, home, monkeypatch)
        FakePopen.stdout_lines = events({"type": "message", "role": "assistant", "content": "• Hunt"}, RESULT)
        assert b.backend.summarize("Summarize.", "long text") == "• Hunt"
        cmd, kw = FakePopen.calls[0]
        assert cmd[cmd.index("-m") + 1] == "flash" and kw["cwd"] != str(kb.root)
        assert FakePopen.last.system == "Summarize."

    def test_not_installed(self, kb, home, monkeypatch):
        b = self.make(kb, home, monkeypatch)
        b.backend.exe = None
        assert b.ask("hi", None, None, None).error == "not_installed"


def test_model_names():
    assert base.model_name("gemini-3.8-flash") == "Gemini 3.8 Flash"
    assert base.model_name("gemini-3-pro-preview") == "Gemini 3 Pro Preview"
