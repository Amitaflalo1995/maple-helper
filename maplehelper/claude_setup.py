"""Detect, install and sign in to Claude Code (the player's own Claude account)."""
from __future__ import annotations

import json
import shlex
import subprocess
import sys

from .brain import CREATE_NO_WINDOW, child_env, find_claude

CREATE_NEW_CONSOLE = 0x00000010 if sys.platform == "win32" else 0
INSTALL_CMD = "irm https://claude.ai/install.ps1 | iex"
INSTALL_CMD_MAC = "curl -fsSL https://claude.ai/install.sh | bash"


def account() -> dict:
    """{'status': 'not_installed' | 'logged_out' | 'ok', 'email': str | None}"""
    exe = find_claude()
    if not exe:
        return {"status": "not_installed", "email": None}
    try:
        r = subprocess.run([exe, "auth", "status"], capture_output=True, timeout=20, env=child_env(),
                           creationflags=CREATE_NO_WINDOW)
        data = json.loads(r.stdout.decode("utf-8", errors="replace") or "{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {"status": "logged_out", "email": None}
    if not data.get("loggedIn"):
        return {"status": "logged_out", "email": None}
    return {"status": "ok", "email": data.get("email")}


def status() -> str:
    """'not_installed' | 'logged_out' | 'ok'"""
    return account()["status"]


def logout() -> bool:
    """Sign Claude Code out of the current account (the next sign-in can pick another one)."""
    exe = find_claude()
    if not exe:
        return False
    try:
        r = subprocess.run([exe, "auth", "logout"], capture_output=True, timeout=30, env=child_env(),
                           creationflags=CREATE_NO_WINDOW)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _applescript_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _in_terminal(command: str) -> subprocess.Popen:
    """macOS: run a shell command in a new Terminal window (the player sees progress and prompts)."""
    return subprocess.Popen(["osascript", "-e", f"tell application \"Terminal\" to do script {_applescript_string(command)}",
                             "-e", 'tell application "Terminal" to activate'])


def install() -> subprocess.Popen:
    """Run the official installer in a visible console so the player sees its progress."""
    if sys.platform == "darwin":
        return _in_terminal(f"{INSTALL_CMD_MAC}; echo; echo 'Done - you can close this window.'")
    return subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                             f"{INSTALL_CMD}; Write-Host ''; Write-Host 'Done - you can close this window.'; pause"],
                            creationflags=CREATE_NEW_CONSOLE)


def login() -> subprocess.Popen | None:
    """Official sign-in flow (opens the browser); visible console for the code prompt if needed."""
    exe = find_claude()
    if not exe:
        return None
    if sys.platform == "darwin":
        return _in_terminal(f"{shlex.quote(exe)} auth login")
    return subprocess.Popen([exe, "auth", "login"], creationflags=CREATE_NEW_CONSOLE)


def test_api_key(key: str) -> bool:
    import urllib.request
    import urllib.error
    req = urllib.request.Request("https://api.anthropic.com/v1/models",
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


# API keys live in Windows Credential Manager / the macOS Keychain, never in plain files.
KEYRING_SERVICE = "MapleHelper"


def save_api_key(key: str) -> None:
    import keyring
    keyring.set_password(KEYRING_SERVICE, "anthropic_api_key", key)


def delete_api_key() -> None:
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, "anthropic_api_key")
    except Exception:
        pass


def load_api_key() -> str | None:
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, "anthropic_api_key")
    except Exception:
        return None
