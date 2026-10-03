"""Gemini through the player's own Gemini CLI install (their Google account, or a Gemini API key).

Each question runs `gemini -p` locked down: read-only tools (read_file, grep_search, glob) in the
knowledge-base folder, no extensions, MCP servers, hooks or context files. The CLI gets a home of
its own inside Maple Helper's data folder (GEMINI_CLI_HOME), so the player's own Gemini setup never
reaches the answers, and the Google sign-in lives there too. Our instructions replace the CLI's
system prompt (GEMINI_SYSTEM_MD). The screenshot is a temporary file the question points at
(@name), and the answer streams back token by token.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .base import CREATE_NO_WINDOW, Provider, RawResult, classify_error, child_env, find_posix, http_ok, \
    open_login, run_installer

log = logging.getLogger(__name__)
STALL_TIMEOUT_S = 150    # no output for this long = stuck (tool calls and streaming print all along)

# Gemini CLI is an npm package (Node.js 20+): the installer brings Node.js along when it's missing or too old
INSTALL_CMD = (
    "$v = 0; try { $v = [int]((node -v) -replace '^v(\\d+).*', '$1') } catch {}; "
    "if ($v -lt 20) { winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements "
    "--accept-package-agreements; $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + "
    "[Environment]::GetEnvironmentVariable('Path', 'User') }; "
    "npm.cmd install -g @google/gemini-cli; "
    # done: the window closes by itself (it stays open, with npm's error, only when the install failed)
    "if ($LASTEXITCODE -eq 0) { exit }")
INSTALL_CMD_MAC = ("if command -v brew >/dev/null 2>&1; then brew install gemini-cli; "
                   "else npm install -g @google/gemini-cli; fi")
POSIX_DIRS = ["~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "~/.npm-global/bin"]
PACKAGE = Path("node_modules") / "@google" / "gemini-cli" / "bundle" / "gemini.js"

# the aliases the CLI resolves to Google's newest model of each kind; None = its own default ("auto")
MODELS: list[tuple[str | None, str]] = [(None, "Auto"), ("pro", "Pro"), ("flash", "Flash")]
SAVER_MODEL = "flash"

# Gemini reads the knowledge base with its own read-only file tools
TOOLS_NOTE = ("\nTools: you read the knowledge base with read_file, grep_search and glob in the current "
              "directory. You cannot write files, run commands or use the network.")

# The settings of Maple Helper's own Gemini home. Everything that could reach beyond the knowledge
# base is off; selectedType picks the account login or the API key (the player's choice).
LOCKED_SETTINGS = {
    "tools": {"core": ["read_file", "grep_search", "glob"]},
    "mcp": {"allowed": []},
    "hooksConfig": {"enabled": False},
    "context": {"fileName": ["MAPLEHELPER_NO_CONTEXT.md"]},     # no GEMINI.md files from the folders
    "privacy": {"usageStatisticsEnabled": False},
    "telemetry": {"enabled": False},
    "general": {"checkpointing": {"enabled": False}, "enableAutoUpdate": False},
    "advanced": {"autoConfigureMemory": False},
}
# environment that would point the CLI at another account, endpoint or credential store
FOREIGN_ENV = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_GCA",
               "GOOGLE_GEMINI_BASE_URL", "GOOGLE_VERTEX_BASE_URL", "GOOGLE_CLOUD_ACCESS_TOKEN", "NO_BROWSER",
               "GEMINI_SYSTEM_MD", "GEMINI_CLI_SYSTEM_SETTINGS_PATH", "GEMINI_FORCE_ENCRYPTED_FILE_STORAGE",
               "GEMINI_MODEL")


def home() -> Path:
    """Maple Helper's own Gemini home (settings, sign-in): GEMINI_CLI_HOME."""
    from ..store import DATA_DIR
    return DATA_DIR / "gemini"


def prepare_home(api_key: bool) -> Path:
    """Write the locked settings (only when they changed: answers and summaries can start together)."""
    d = home() / ".gemini"
    d.mkdir(parents=True, exist_ok=True)
    settings = {**LOCKED_SETTINGS, "security": {"auth": {"selectedType": "gemini-api-key" if api_key
                                                         else "oauth-personal"}}}
    text = json.dumps(settings, indent=2)
    path = d / "settings.json"
    try:
        if path.read_text(encoding="utf-8") == text:
            return home()
    except OSError:
        pass
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return home()


def find_node() -> str | None:
    """node.exe: on PATH, else where the Node.js installer puts it (PATH is the app's own, from before an install)."""
    p = shutil.which("node")
    if p and p.lower().endswith(".exe"):
        return p
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("LOCALAPPDATA", "")):
        c = Path(base) / "nodejs" / "node.exe"
        if base and c.exists():
            return str(c)
    return None


def find_windows() -> str | None:
    """gemini.js of an npm install. Never the gemini.cmd shim: stopping an answer would only stop cmd.exe,
    and the node.exe under it would go on. The shim still has to be there: npm writes it last, so an
    install that's still unpacking doesn't count as installed yet."""
    dirs = [Path(os.environ.get("APPDATA", "")) / "npm"]
    shim = shutil.which("gemini")
    if shim:
        dirs.insert(0, Path(shim).parent)      # an npm install with its own prefix
    for d in dirs:
        script = d / PACKAGE
        if script.exists() and (d / "gemini.cmd").exists():
            return str(script)
    return None


def find_gemini() -> str | None:
    """Locate the Gemini CLI (npm or Homebrew); on Windows its script, run with node.exe (see command())."""
    return find_windows() if sys.platform == "win32" else find_posix("gemini", POSIX_DIRS)


def command(exe: str, platform: str = sys.platform) -> list[str] | None:
    """How to start it: [node.exe, gemini.js] on Windows (None without Node.js), the executable elsewhere."""
    if platform != "win32":
        return [exe]
    node = find_node()
    return [node, exe] if node else None


def env(api_key: str | None = None, system_md: str | None = None) -> dict:
    e = child_env(POSIX_DIRS)
    for k in FOREIGN_ENV:
        e.pop(k, None)
    e["GEMINI_CLI_HOME"] = str(home())
    e["GEMINI_CLI_NO_RELAUNCH"] = "true"     # one process: stopping it stops the answer (no node child left over)
    if api_key:
        e["GEMINI_API_KEY"] = api_key
    if system_md:
        e["GEMINI_SYSTEM_MD"] = system_md
    return e


def gemini_command(start: list[str], model: str | None = None, image_dir=None) -> list[str]:
    """The question itself comes on stdin (-p "" adds nothing to it)."""
    cmd = [*start, "-p", "", "-o", "stream-json", "--skip-trust", "--approval-mode", "plan", "-e", "none"]
    if image_dir:
        cmd += ["--include-directories", str(image_dir)]
    if model:
        cmd += ["-m", model]
    return cmd


def classify(text: str) -> str | None:
    t = text.lower()
    if ("api key not valid" in t or "api_key_invalid" in t or "unauthenticated" in t or "manual authorization" in t
            or "please set an auth method" in t or "invalid_grant" in t or "login required" in t):
        return "not_logged_in"
    if "quota" in t or "resource_exhausted" in t or "429" in t:
        return "usage_limit"
    return classify_error(text)


def parse_events(lines, on_delta=None) -> tuple[str, dict | None, list[str], str | None]:
    """(answer text, the result event, error messages, session id) from stream-json output.
    The answer is the text after the last tool call: earlier text is a lead-in ("I'll check the database")."""
    current, result, errors, session = "", None, [], None
    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="replace")
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        t = ev.get("type")
        if t == "init":
            session = ev.get("session_id") or session
        elif t == "message" and ev.get("role") == "assistant":
            current += str(ev.get("content") or "")
            if on_delta:
                on_delta(current)
        elif t == "tool_use":
            current = ""
        elif t == "error":
            errors.append(str(ev.get("message", "")))
        elif t == "result":
            result = ev
    return current, result, errors, session


def answering_model(result: dict | None) -> str | None:
    """The model that wrote the answer: the result's per-model stats name it ("gemini-3.8-flash")."""
    models = ((result or {}).get("stats") or {}).get("models")
    if not isinstance(models, dict):
        return None
    out = [name for name, s in models.items() if isinstance(s, dict) and s.get("output_tokens")]
    return (out or list(models) or [None])[-1]


def to_result(text: str, result: dict | None, errors: list[str], stderr: str) -> RawResult:
    if not result or result.get("status") != "success":
        detail = "\n".join(errors) + "\n" + str(((result or {}).get("error") or {}).get("message", "")) + "\n" + stderr
        log.warning("Gemini gave no answer: %s", detail.strip()[-1500:])   # the cause, for "Report a problem"
        return RawResult(error=classify(detail) or ("api_error" if result else "no_result"))
    return RawResult(text=text, model=answering_model(result))


def forget_session(session: str | None) -> None:
    """The CLI saves every run as a chat file in its home; Maple Helper keeps nothing (like Claude's
    --no-session-persistence)."""
    if not session:
        return
    for f in (home() / ".gemini" / "tmp").glob(f"*/chats/session-*{session[:8]}*"):
        try:
            f.unlink()
        except OSError:
            pass


def read_account() -> dict:
    """The Google sign-in in Maple Helper's Gemini home: {'status': 'ok' | 'logged_out', 'email'}."""
    d = home() / ".gemini"
    try:
        creds = json.loads((d / "oauth_creds.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        creds = None
    if not isinstance(creds, dict) or not (creds.get("refresh_token") or creds.get("access_token")):
        return {"status": "logged_out", "email": None}
    try:
        email = json.loads((d / "google_accounts.json").read_text(encoding="utf-8")).get("active")
    except (OSError, ValueError, AttributeError):
        email = None
    return {"status": "ok", "email": email if isinstance(email, str) else None}


class Gemini(Provider):
    name = "gemini"
    label = "Gemini"
    keyring_user = "gemini_api_key"
    model_setting = "gemini_model"
    saver_model = SAVER_MODEL
    reports_usage = False     # the CLI doesn't report the plan's quota

    def find_exe(self) -> str | None:
        return find_gemini()

    def models(self) -> list[tuple[str | None, str]]:
        return list(MODELS)

    def account(self) -> dict:
        exe = find_gemini()
        if not exe or not command(exe):
            # no CLI, or no Node.js to run it: the installer brings both
            return {"status": "not_installed", "email": None}
        return read_account()

    def logout(self) -> bool:
        """Forget the Google sign-in (only Maple Helper's: the player's own Gemini CLI keeps its own)."""
        d = home() / ".gemini"
        try:
            (d / "oauth_creds.json").unlink(missing_ok=True)
            accounts = d / "google_accounts.json"
            if accounts.exists():
                accounts.write_text(json.dumps({"active": None, "old": []}), encoding="utf-8")
            return True
        except OSError:
            return False

    def login(self) -> subprocess.Popen | None:
        """Official Google sign-in: the CLI asks before it opens the browser ("y"), then answers one tiny
        question and exits 0. No window of its own."""
        exe = find_gemini()
        start = command(exe) if exe else None
        if not start:
            return None
        h = prepare_home(api_key=False)
        return open_login(start, ["-p", "Reply with OK.", "-o", "json", "--skip-trust", "--approval-mode", "plan",
                                  "-e", "none", "-m", SAVER_MODEL], env(), answer="y\n", cwd=str(h))

    def install(self) -> subprocess.Popen:
        return run_installer(INSTALL_CMD, INSTALL_CMD_MAC)

    def test_api_key(self, key: str) -> bool:
        return http_ok("https://generativelanguage.googleapis.com/v1beta/models", {"x-goog-api-key": key})

    def backend(self, brain):
        return GeminiBackend(brain)


class GeminiBackend:
    """Runs questions for a Brain through `gemini -p`, one fresh process per question. No warm process:
    the CLI waits only half a second for the question on stdin."""

    def __init__(self, brain):
        self.brain = brain
        self.exe = find_gemini()
        self._proc: subprocess.Popen | None = None

    def prewarm(self) -> None:
        pass

    def shutdown(self) -> None:
        self.cancel()

    def cancel(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.kill()

    def _exec(self, instructions: str, stdin_text: str, cwd: str, model: str | None, image_dir=None,
              on_delta=None, answer: bool = True, timeout: float | None = None) -> RawResult:
        """answer=False (a summary): not tracked as the answer cancel() stops."""
        start = command(self.exe) if self.exe else None
        if not start:
            return RawResult(error="launch_failed: no Node.js")
        api_key = self.brain.api_key
        prepare_home(api_key=bool(api_key))
        fd, system_md = tempfile.mkstemp(prefix="maplehelper-gemini-", suffix=".md")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(instructions)
        session = None
        try:
            try:
                p = subprocess.Popen(gemini_command(start, model, image_dir), cwd=cwd, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env(api_key, system_md),
                                     creationflags=CREATE_NO_WINDOW)
            except OSError as e:
                return RawResult(error=f"launch_failed: {e}")
            if answer:
                self._proc = p
            # the CLI logs to stderr while it works: drain it so a full pipe never stalls the run
            err: list[bytes] = []
            reader = threading.Thread(target=lambda: err.extend(iter(lambda: p.stderr.read(4096), b"")), daemon=True)
            reader.start()
            try:
                p.stdin.write(stdin_text.encode("utf-8"))
                p.stdin.close()
            except OSError:        # it exited at once: stderr says why
                pass
            # stuck = no output for a while (or past a summary's own time limit)
            last, began, stalled = [time.monotonic()], time.monotonic(), threading.Event()

            def watchdog():
                while p.poll() is None:
                    now = time.monotonic()
                    if now - last[0] > STALL_TIMEOUT_S or (timeout and now - began > timeout):
                        stalled.set()
                        p.kill()
                        return
                    time.sleep(1)
            threading.Thread(target=watchdog, daemon=True).start()

            def lines():
                for line in p.stdout:
                    last[0] = time.monotonic()
                    yield line
            text, result, errors, session = parse_events(lines(), on_delta)
            p.wait()
            reader.join(timeout=5)
            stderr = b"".join(err).decode("utf-8", errors="replace")
            if stalled.is_set():
                log.warning("Gemini stalled, stopped: %s", stderr[-1000:])
                return RawResult(error="timeout")
            return to_result(text, result, errors, stderr)
        finally:
            forget_session(session)
            try:
                os.remove(system_md)
            except OSError:
                pass

    def run(self, prompt: str, screenshot_jpeg: bytes | None, on_raw_delta=None, model: str | None = None,
            tools: bool = True) -> RawResult:
        """model: this call's own (None: the player's). tools is Claude's: Gemini reads files only when asked to."""
        b = self.brain
        with tempfile.TemporaryDirectory(prefix="maplehelper-shots-") as shots:
            names = []
            for i, jpeg in enumerate(screenshot_jpeg if isinstance(screenshot_jpeg, list) else [screenshot_jpeg]):
                if jpeg:
                    names.append(f"maplehelper-shot-{i}.jpg")
                    Path(shots, names[-1]).write_bytes(jpeg)
            # "@name" attaches a file; the CLI finds it in the extra folder
            question = prompt + ("\n\n" + " ".join("@" + n for n in names) if names else "")
            return self._exec(b.system_prompt() + TOOLS_NOTE, question, str(b.kb.root), model or b.model,
                              shots if names else None, on_raw_delta)

    def summarize(self, instructions: str, text: str, timeout: int = 90) -> str | None:
        """One short call on Flash: session summaries and guide summaries."""
        if not self.exe:
            return None
        with tempfile.TemporaryDirectory(prefix="maplehelper-summary-") as empty:
            r = self._exec(instructions, text, empty, SAVER_MODEL, answer=False, timeout=timeout)
        return r.text.strip() or None
