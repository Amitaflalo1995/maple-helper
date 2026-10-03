"""What every AI provider shares: process flags, finding the CLI, keyring storage, error codes."""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# no console window flashing up on Windows; elsewhere creationflags must stay 0
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
CREATE_NEW_CONSOLE = 0x00000010 if sys.platform == "win32" else 0

# API keys live in Windows Credential Manager / the macOS Keychain, never in plain files.
KEYRING_SERVICE = "MapleHelper"


@dataclass
class RawResult:
    """One CLI run: the raw answer (visible text + @@META@@ JSON), or an error code."""
    text: str = ""
    error: str | None = None
    cost_usd: float | None = None
    limits: dict | None = None     # plan usage, when the CLI reports it with the answer (Claude Code, see usage.py)
    model: str | None = None       # the model that answered, when the CLI says ("claude-sonnet-5")


def model_name(model_id: str) -> str:
    """A readable name: "claude-sonnet-5-20260101" -> "Sonnet 5", "claude-opus-4-5" -> "Opus 4.5",
    "gpt-6.1-sol" -> "GPT-6.1-Sol"."""
    import re
    m = re.fullmatch(r"claude-([a-z]+)-(\d+(?:-\d+)?)(?:-\d{8})?(?:\[.*\])?", model_id or "")
    if m:
        return f"{m.group(1).capitalize()} {m.group(2).replace('-', '.')}"
    if (model_id or "").startswith("gpt-"):
        return "GPT-" + "-".join(w.capitalize() for w in model_id[4:].split("-"))
    if (model_id or "").startswith("gemini-"):      # "gemini-3.8-flash-lite" -> "Gemini 3.8 Flash Lite"
        return " ".join(w if w[:1].isdigit() else w.capitalize() for w in model_id.split("-"))
    return model_id or ""


def find_posix(name: str, dirs: list[str]) -> str | None:
    p = shutil.which(name)
    if p:
        return p
    for d in dirs:
        c = Path(d).expanduser() / name
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def find_windows_exe(name: str, candidates: list[Path]) -> str | None:
    """A real .exe on PATH, else a known install spot."""
    p = shutil.which(name)
    if p and p.lower().endswith(".exe"):
        # which() takes the extension from PATHEXT (".EXE"). Claude Code started as claude.EXE hangs when it
        # re-runs itself as its built-in rg, so the path always ends in a lowercase ".exe"
        return p[:-4] + ".exe"
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def child_env(dirs: list[str], env: dict | None = None) -> dict:
    """Environment for a CLI: on macOS the install folders join PATH (an npm install needs node)."""
    env = dict(os.environ if env is None else env)
    if sys.platform != "win32":
        extra = [str(Path(d).expanduser()) for d in dirs]
        env["PATH"] = os.pathsep.join([env.get("PATH") or "/usr/bin:/bin"] + extra)
    return env


def _applescript_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def in_terminal(command: str) -> subprocess.Popen:
    """macOS: run a shell command in a new Terminal window (the player sees progress and prompts)."""
    return subprocess.Popen(["osascript", "-e", f"tell application \"Terminal\" to do script {_applescript_string(command)}",
                             "-e", 'tell application "Terminal" to activate'])


_login: subprocess.Popen | None = None


def open_login(exe: str, args: list[str], env: dict | None = None, cwd: str | None = None,
               keep_stdin: bool = False, on_line=None) -> subprocess.Popen | None:
    """The official sign-in, with no console window: the CLI opens the browser itself and waits for it there.
    Its output goes to the log (it says why, when a sign-in fails). None when it couldn't start.
    keep_stdin: the CLI waits for a code the player pastes (send_login_input). on_line(text): each output
    line, before it's logged (Gemini's sign-in link is opened from there)."""
    global _login
    stop_login()   # one left waiting still holds its local port (Codex: 1455), so a new one would fail
    try:
        p = subprocess.Popen([exe, *args], stdin=subprocess.PIPE if keep_stdin else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=cwd,
                             creationflags=CREATE_NO_WINDOW)
    except OSError:
        log.warning("sign-in can't start: %s", exe, exc_info=True)
        return None

    def drain():
        for line in p.stdout:
            text = line.decode("utf-8", errors="replace").strip()
            if text and on_line:
                try:
                    on_line(text)
                except Exception:      # noqa: BLE001 - the sign-in goes on; the log says why it didn't open
                    log.warning("sign-in line handler failed", exc_info=True)
            if text:   # the one-time sign-in links stay out of the log
                text = re.sub(r"https?://\S+", "<link>", text)
                log.info("sign-in: %s", re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "<email>", text))   # no email in reports
        if p.wait():
            log.warning("sign-in ended with code %s", p.returncode)
    threading.Thread(target=drain, daemon=True).start()
    _login = p
    return p


def send_login_input(text: str) -> bool:
    """Type into the sign-in that's waiting (a code pasted from the browser). False when none is waiting."""
    p = _login
    if not p or p.poll() is not None or not p.stdin:
        return False
    try:
        p.stdin.write(text.encode("utf-8"))
        p.stdin.flush()
        return True
    except OSError:
        return False


def stop_login() -> None:
    """End a sign-in that's still waiting for the browser (the player gave up or closed the window)."""
    global _login
    if _login and _login.poll() is None:
        _login.kill()
    _login = None


def login_failed(p: subprocess.Popen | None) -> bool:
    """The sign-in process ended without success (a successful one exits 0)."""
    return p is not None and p.poll() is not None and p.returncode != 0


def run_installer(win_cmd: str, mac_cmd: str) -> subprocess.Popen:
    """Run an official installer in a visible console so the player sees its progress."""
    if sys.platform == "darwin":
        return in_terminal(f"{mac_cmd}; echo; echo 'Done - you can close this window.'")
    return subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                             f"{win_cmd}; Write-Host ''; Write-Host 'Done - you can close this window.'; pause"],
                            creationflags=CREATE_NEW_CONSOLE)


def http_ok(url: str, headers: dict) -> bool:
    import http.client
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15) as r:
            return r.status == 200
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError):
        return False


def classify_error(text: str) -> str | None:
    t = text.lower()
    if ("not logged in" in t or "please run /login" in t or "invalid api key" in t or "invalid_api_key" in t
            or "401 unauthorized" in t or "authentication" in t):
        return "not_logged_in"
    if "usage limit" in t or "rate limit" in t or "limit reached" in t or "resets" in t:
        return "usage_limit"
    if "enotfound" in t or "econnrefused" in t or "network" in t or "fetch failed" in t:
        return "offline"
    return None


class Provider:
    """One AI CLI the player signs in to. Subclasses fill in the specifics."""
    name = ""
    label = ""
    keyring_user = ""
    model_setting = ""       # settings key holding this provider's model (None = the CLI's default)
    saver_model = None       # lighter model for saver mode; None = keep the model, answers just get shorter
    reports_usage = False    # the CLI reports the player's plan usage (drives the usage meter)
    login_code = False       # the sign-in ends with a code the player pastes back (submit_login_code)

    def submit_login_code(self, code: str) -> bool:
        return False

    def find_exe(self) -> str | None:
        raise NotImplementedError

    def models(self) -> list[tuple[str | None, str]]:
        """The models a player can pick: [(value for the CLI, name to show)]; None = the CLI's default."""
        return []

    def read_limits(self) -> dict | None:
        """The plan usage read on demand (usage.parse shape); None when the CLI only reports it with answers."""
        return None

    def account(self) -> dict:
        """{'status': 'not_installed' | 'logged_out' | 'ok', 'email': str | None, ...}"""
        raise NotImplementedError

    def status(self) -> str:
        return self.account()["status"]

    def logout(self) -> bool:
        raise NotImplementedError

    def login(self) -> subprocess.Popen | None:
        raise NotImplementedError

    def install(self) -> subprocess.Popen:
        raise NotImplementedError

    def test_api_key(self, key: str) -> bool:
        raise NotImplementedError

    def backend(self, brain):
        """The object that runs questions for `brain` (see claude.ClaudeBackend)."""
        raise NotImplementedError

    # keys ------------------------------------------------------------------
    def save_api_key(self, key: str) -> None:
        import keyring
        keyring.set_password(KEYRING_SERVICE, self.keyring_user, key)

    def delete_api_key(self) -> None:
        try:
            import keyring
            keyring.delete_password(KEYRING_SERVICE, self.keyring_user)
        except Exception:
            pass

    def load_api_key(self) -> str | None:
        try:
            import keyring
            return keyring.get_password(KEYRING_SERVICE, self.keyring_user)
        except Exception:
            return None
