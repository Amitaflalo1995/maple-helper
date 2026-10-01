"""Codex through the player's own Codex CLI install (their ChatGPT account, or an OpenAI API key).

Each question runs `codex exec` locked down: read-only sandbox in the knowledge-base
folder, the player's own Codex config, rules and MCP servers ignored, nothing saved.
The screenshot is attached as a temporary file. Codex has no token stream, so the
answer arrives whole (the last agent message of the run).
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from .base import CREATE_NEW_CONSOLE, CREATE_NO_WINDOW, Provider, RawResult, classify_error, child_env, find_posix, \
    find_windows_exe, http_ok, in_terminal, run_installer

INSTALL_CMD = "irm https://chatgpt.com/codex/install.ps1 | iex"
INSTALL_CMD_MAC = "curl -fsSL https://chatgpt.com/codex/install.sh | sh"
POSIX_DIRS = ["~/.local/bin", "~/.codex/bin", "/opt/homebrew/bin", "/usr/local/bin", "~/.npm-global/bin"]

# Codex reads the knowledge base with shell commands instead of Claude's Read/Grep/Glob tools
TOOLS_NOTE = ("\nTools: you read the knowledge base with read-only shell commands in the current directory "
              "(rg, grep, Select-String, Get-Content, cat). You cannot write files or use the network.")


def store_apps() -> list[Path]:
    """codex.exe inside OpenAI's desktop app from the Microsoft Store (the "ChatGPT"/Codex app), newest first.
    Its folder (WindowsApps) can't be listed, but Windows records each installed package in the registry."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\Local Settings\Software\Microsoft"
                                                       r"\Windows\CurrentVersion\AppModel\Repository\Packages")
    except (ImportError, OSError):
        return []
    found = []
    i = 0
    while True:
        try:
            name = winreg.EnumKey(key, i)
        except OSError:
            break
        i += 1
        if not name.startswith("OpenAI."):
            continue
        try:
            root = winreg.QueryValueEx(winreg.OpenKey(key, name), "PackageRootFolder")[0]
        except OSError:
            continue
        version = tuple(int(x) for x in name.split("_")[1].split(".") if x.isdigit()) if "_" in name else ()
        found.append((version, Path(root) / "app" / "resources" / "codex.exe"))
    return [p for _, p in sorted(found, reverse=True)]


def find_windows() -> str | None:
    # only a real .exe: an npm .cmd shim runs through cmd.exe, which mangles the quoted instructions
    local, appdata = os.environ.get("LOCALAPPDATA", ""), os.environ.get("APPDATA", "")
    vendor = Path(appdata) / "npm" / "node_modules" / "@openai" / "codex" / "vendor"
    return find_windows_exe("codex", [
        Path(local) / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe",
        vendor / "x86_64-pc-windows-msvc" / "codex" / "codex.exe",
        vendor / "aarch64-pc-windows-msvc" / "codex" / "codex.exe",
        *store_apps(),
    ])


def find_codex() -> str | None:
    """Locate the Codex CLI (official installer, npm or Homebrew)."""
    return find_windows() if sys.platform == "win32" else find_posix("codex", POSIX_DIRS)


def env(api_key: str | None = None) -> dict:
    e = child_env(POSIX_DIRS)
    if api_key:
        e["CODEX_API_KEY"] = api_key
    else:
        e.pop("CODEX_API_KEY", None)   # use the player's ChatGPT login
    return e


def codex_command(exe: str, workdir, instructions: str, model: str | None = None, image=None,
                  platform: str = sys.platform, extra: tuple = ()) -> list[str]:
    cmd = [exe, "exec"]
    if image:
        # --image takes several values: anywhere later it would swallow the "-" stdin marker
        cmd += ["--image", str(image)]
    # json.dumps gives a valid TOML basic string (same escapes), so newlines and quotes survive -c
    cmd += ["--json", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
            "-s", "read-only", "-C", str(workdir), "-c", "developer_instructions=" + json.dumps(instructions)]
    if platform == "win32":
        # without it, the read-only sandbox on Windows blocks even reading files
        cmd += ["-c", 'windows.sandbox="unelevated"']
    if model:
        cmd += ["-m", model]
    return cmd + list(extra) + ["-"]


def parse_events(lines, stderr: str = "") -> RawResult:
    """The answer is the run's last agent message; earlier ones are lead-ins ("I'll check the database")."""
    answer, errors, failed = None, [], False
    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="replace")
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue           # Codex logs plain text lines too
        if not isinstance(ev, dict):
            continue
        t = ev.get("type")
        if t == "item.completed" and (ev.get("item") or {}).get("type") == "agent_message":
            answer = ev["item"].get("text") or ""
        elif t == "error":
            errors.append(str(ev.get("message", "")))
        elif t == "turn.failed":
            failed = True
            errors.append(str((ev.get("error") or {}).get("message", "")))
    detail = "\n".join(errors) + "\n" + stderr
    if failed:
        return RawResult(error=classify_error(detail) or "api_error")
    if answer is None:
        return RawResult(error=classify_error(detail) or "no_result")
    return RawResult(text=answer)


LIMITS_REQUEST = ({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "maple_helper", "version": "1"}}},
                  {"method": "initialized"}, {"id": 2, "method": "account/rateLimits/read"})


def read_limits_reply(lines) -> dict | None:
    """The usage from the app-server's reply to request 2 (other lines are notifications)."""
    from .. import usage
    for line in lines:
        try:
            msg = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(msg, dict) and msg.get("id") == 2:
            return usage.parse_codex((msg.get("result") or {}).get("rateLimits"))
    return None


def parse_status(returncode: int, output: str) -> dict:
    """`codex login status` prints e.g. "Logged in using ChatGPT" (it shows no email)."""
    t = output.lower()
    if returncode != 0 or "logged in" not in t or "not logged in" in t:
        return {"status": "logged_out", "email": None, "method": None}
    return {"status": "ok", "email": None, "method": "api_key" if "api key" in t else "chatgpt"}


class Codex(Provider):
    name = "codex"
    label = "ChatGPT"     # what players know it as (it runs through the Codex CLI)
    keyring_user = "openai_api_key"
    model_setting = "codex_model"
    reports_usage = True      # read on demand from the app-server (codex exec doesn't report it)

    def find_exe(self) -> str | None:
        return find_codex()

    def read_limits(self, timeout: float = 20) -> dict | None:
        """The ChatGPT plan usage (5-hour and weekly windows), from `codex app-server`'s
        account/rateLimits/read. None when not installed, signed out, on an API key, or on any error."""
        exe = find_codex()
        if not exe:
            return None
        try:
            p = subprocess.Popen([exe, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, env=env(), creationflags=CREATE_NO_WINDOW)
        except OSError:
            return None
        killer = threading.Timer(timeout, p.kill)
        killer.start()
        try:
            for msg in LIMITS_REQUEST:
                p.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
            p.stdin.flush()
            return read_limits_reply(p.stdout)
        except OSError:
            return None
        finally:
            killer.cancel()
            p.kill()
            p.wait()

    def account(self) -> dict:
        exe = find_codex()
        if not exe:
            return {"status": "not_installed", "email": None, "method": None}
        try:
            r = subprocess.run([exe, "login", "status"], capture_output=True, timeout=20, env=env(),
                               creationflags=CREATE_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            return {"status": "logged_out", "email": None, "method": None}
        out = (r.stdout + r.stderr).decode("utf-8", errors="replace")   # the status goes to stderr
        return parse_status(r.returncode, out)

    def logout(self) -> bool:
        exe = find_codex()
        if not exe:
            return False
        try:
            r = subprocess.run([exe, "logout"], capture_output=True, timeout=30, env=env(),
                               creationflags=CREATE_NO_WINDOW)
            return r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def login(self) -> subprocess.Popen | None:
        """Official ChatGPT sign-in (opens the browser) in a visible console."""
        exe = find_codex()
        if not exe:
            return None
        if sys.platform == "darwin":
            return in_terminal(f"{shlex.quote(exe)} login")
        return subprocess.Popen([exe, "login"], creationflags=CREATE_NEW_CONSOLE)

    def install(self) -> subprocess.Popen:
        return run_installer(INSTALL_CMD, INSTALL_CMD_MAC)

    def test_api_key(self, key: str) -> bool:
        return http_ok("https://api.openai.com/v1/models", {"Authorization": f"Bearer {key}"})

    def backend(self, brain):
        return CodexBackend(brain)


class CodexBackend:
    """Runs questions for a Brain through `codex exec`, one fresh process per question."""

    def __init__(self, brain):
        self.brain = brain
        self.exe = find_codex()
        self._proc: subprocess.Popen | None = None

    def prewarm(self) -> None:
        # the screenshot must be on the command line, so a process can't be started before the question
        pass

    def shutdown(self) -> None:
        self.cancel()

    def cancel(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.kill()

    def _exec(self, cmd: list[str], stdin_text: str, cwd: str, api_key: str | None,
              timeout: int | None = None) -> RawResult:
        try:
            self._proc = p = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                              stderr=subprocess.PIPE, env=env(api_key), creationflags=CREATE_NO_WINDOW)
        except OSError as e:
            return RawResult(error=f"launch_failed: {e}")
        # Codex logs to stderr while it works: drain it so a full pipe never stalls the run
        err: list[bytes] = []
        reader = threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True)
        reader.start()
        killer = threading.Timer(timeout, p.kill) if timeout else None
        if killer:
            killer.start()
        p.stdin.write(stdin_text.encode("utf-8"))
        p.stdin.close()
        lines = list(p.stdout)
        p.wait()
        if killer:
            killer.cancel()
        reader.join(timeout=5)
        return parse_events(lines, b"".join(err).decode("utf-8", errors="replace"))

    def run(self, prompt: str, screenshot_jpeg: bytes | None, on_raw_delta=None) -> RawResult:
        b = self.brain
        image = None
        try:
            if screenshot_jpeg:
                fd, image = tempfile.mkstemp(prefix="maplehelper-shot-", suffix=".jpg")
                with os.fdopen(fd, "wb") as f:
                    f.write(screenshot_jpeg)
            cmd = codex_command(self.exe, b.kb.root, b.system_prompt() + TOOLS_NOTE, b.model, image)
            r = self._exec(cmd, prompt, str(b.kb.root), b.api_key)
        finally:
            if image:
                try:
                    os.remove(image)
                except OSError:
                    pass
        if r.text and on_raw_delta:
            on_raw_delta(r.text)
        return r

    def summarize(self, instructions: str, text: str, timeout: int = 90) -> str | None:
        """One short call with low reasoning effort: session summaries and guide summaries."""
        if not self.exe:
            return None
        with tempfile.TemporaryDirectory(prefix="maplehelper-summary-") as empty:
            cmd = codex_command(self.exe, empty, instructions, self.brain.model,
                                extra=("-c", 'model_reasoning_effort="low"'))
            r = self._exec(cmd, text, empty, self.brain.api_key, timeout=timeout)
        return r.text.strip() or None
