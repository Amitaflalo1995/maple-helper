"""What every AI provider shares: process flags, finding the CLI, keyring storage, error codes."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

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
    limits: dict | None = None     # plan usage, when the CLI reports it (Claude Code only, see usage.py)


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


def run_installer(win_cmd: str, mac_cmd: str) -> subprocess.Popen:
    """Run an official installer in a visible console so the player sees its progress."""
    if sys.platform == "darwin":
        return in_terminal(f"{mac_cmd}; echo; echo 'Done - you can close this window.'")
    return subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                             f"{win_cmd}; Write-Host ''; Write-Host 'Done - you can close this window.'; pause"],
                            creationflags=CREATE_NEW_CONSOLE)


def http_ok(url: str, headers: dict) -> bool:
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError):
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

    def find_exe(self) -> str | None:
        raise NotImplementedError

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
