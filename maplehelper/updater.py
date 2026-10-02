"""Knowledge-base updates from GitHub Releases (players never hit meowdb.com directly).

A release carries kb-manifest.json: {"version": "2026.10.02", "url": ".../kb.zip", "sha256": "..."}.
The zip is unpacked into %APPDATA%/MapleHelper/kb, which then wins over the bundled copy.
"""
from __future__ import annotations

import hashlib
import http.client
import io
import re
import sys
import json
import shutil
import time
import urllib.error
import urllib.request
import zipfile

from .store import USER_KB, kb_dir

# Set when the GitHub repository exists (see README, "Publishing").
GITHUB_REPO = "Amitaflalo1995/maple-helper"
MANIFEST_URL = f"https://github.com/{GITHUB_REPO}/releases/latest/download/kb-manifest.json" if GITHUB_REPO else ""


def local_version() -> str:
    try:
        return json.loads((kb_dir() / "meta.json").read_text(encoding="utf-8")).get("version", "")
    except (OSError, json.JSONDecodeError):
        return ""


def changelog() -> list[dict]:
    """Patch notes of recent KB updates, newest first (written by tools/kb_release.py)."""
    try:
        log = json.loads((kb_dir() / "changelog.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [e for e in log if isinstance(e, dict) and e.get("version")] if isinstance(log, list) else []


def changes_since(version: str) -> list[dict]:
    """The updates a player hasn't seen yet: every entry newer than the KB they had."""
    return [e for e in changelog() if str(e["version"]) > version]


def _get(url: str, timeout: int = 30) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MapleHelper"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ValueError, OSError):
        return None


def update_kb(before_swap=None) -> bool:
    """Download a newer knowledge base if one is published. Returns True when updated."""
    return fetch_kb(before_swap) == "updated"


def fetch_kb(before_swap=None) -> str:
    """"updated", "uptodate" or "failed". before_swap() runs right before the folders are swapped (the app
    stops the AI process working inside the KB there); returning False postpones the update."""
    if not MANIFEST_URL:
        return "uptodate"
    raw = _get(MANIFEST_URL, timeout=15)
    if not raw:
        return "failed"
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError:
        return "failed"
    if not isinstance(manifest, dict) or not manifest.get("url"):
        return "failed"
    if str(manifest.get("version", "")) <= local_version():
        return "uptodate"
    data = _get(manifest["url"], timeout=300)
    if not data or hashlib.sha256(data).hexdigest() != manifest.get("sha256"):
        return "failed"
    tmp = USER_KB.with_name("kb.new")
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            z.extractall(tmp)
    except zipfile.BadZipFile:
        shutil.rmtree(tmp, ignore_errors=True)
        return "failed"
    if not (tmp / "index.json").exists():
        shutil.rmtree(tmp, ignore_errors=True)
        return "failed"
    meta_path = tmp / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta["version"] = manifest["version"]
    meta_path.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    # swap by renames: on Windows a folder another process works in (the AI runs inside the KB)
    # can't be removed or renamed; then keep the current KB intact and try again next time
    if before_swap is not None and before_swap() is False:
        shutil.rmtree(tmp, ignore_errors=True)
        return "failed"
    old = USER_KB.with_name("kb.old")
    shutil.rmtree(old, ignore_errors=True)
    try:
        if USER_KB.exists():
            USER_KB.rename(old)
        tmp.rename(USER_KB)
    except OSError:
        if old.exists() and not USER_KB.exists():
            old.rename(USER_KB)
        shutil.rmtree(tmp, ignore_errors=True)
        return "failed"
    shutil.rmtree(old, ignore_errors=True)
    return "updated"


# ---------------------------------------------------------------- app updates

SETUP_ASSET = "MapleHelper-Setup.exe"
SUMS_ASSET = "SHA256SUMS.txt"     # "<sha256>  <file name>" lines, published with every release


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def _asset(rel: dict, name: str) -> dict | None:
    return next((a for a in rel.get("assets", []) or [] if isinstance(a, dict) and a.get("name") == name), None)


def _published_sha256(rel: dict, name: str) -> str | None:
    """The release's own checksum for `name`, from its SHA256SUMS.txt."""
    sums = _asset(rel, SUMS_ASSET)
    raw = _get(sums["browser_download_url"], timeout=30) if sums else None
    if not raw:
        return None
    for line in raw.decode("utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    return None


def _latest_release() -> dict | None:
    raw = _get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest", timeout=15) if GITHUB_REPO else None
    try:
        rel = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None
    if not isinstance(rel, dict) or rel.get("draft") or rel.get("prerelease"):
        return None
    return rel


def newer_release(current: str) -> tuple[str, str] | None:
    """(version, release page URL) when GitHub has a newer release: macOS shows a notice instead of self-updating."""
    rel = _latest_release()
    if not rel or _version_tuple(rel.get("tag_name", "")) <= _version_tuple(current):
        return None
    return rel["tag_name"].lstrip("v"), rel.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases/latest"


def _download(url: str, progress=None, timeout: int = 600) -> bytes | None:
    """The whole file, reporting progress(done_bytes, total_bytes) as it arrives."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MapleHelper"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            total = int(r.headers.get("Content-Length") or 0)
            chunks, done = [], 0
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
            return b"".join(chunks)
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ValueError, OSError):
        return None


def download_app_update(current: str, progress=None) -> str | None:
    """If GitHub has a newer release, download its installer. Returns the installer path.
    progress(done_bytes, total_bytes) is called while it downloads.

    The installer is only kept when its SHA-256 matches the release's SHA256SUMS.txt:
    it is executed on the player's PC, so a truncated or corrupted download must never run.
    """
    rel = _latest_release()
    if not rel or _version_tuple(rel.get("tag_name", "")) <= _version_tuple(current):
        return None
    asset = _asset(rel, SETUP_ASSET)
    want = _published_sha256(rel, SETUP_ASSET) if asset else None
    if not want:
        return None
    path = USER_KB.parent / "updates" / f"MapleHelper-Setup-{rel['tag_name']}.exe"
    try:
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == want:
            return str(path)       # downloaded before (an update skipped at shutdown): no second download
    except OSError:
        pass
    url = asset["browser_download_url"]
    data = _download(url, progress) if progress else _get(url, timeout=600)
    if not data or hashlib.sha256(data).hexdigest() != want:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def remove_old_installers() -> None:
    """Downloaded installers for this version or older are no longer needed (~100 MB each)."""
    from . import __version__
    folder = USER_KB.parent / "updates"
    for f in folder.glob("MapleHelper-Setup-*.exe") if folder.exists() else []:
        if _version_tuple(installer_version(str(f))) <= _version_tuple(__version__):
            try:
                f.unlink()
            except OSError:
                pass


def installer_version(path: str) -> str:
    """'0.4.0' from '.../MapleHelper-Setup-v0.4.0.exe'."""
    m = re.search(r"Setup-v?([\d.]+)\.exe$", str(path))
    return m.group(1) if m else ""


def installer_args(path: str, reopen: bool, lang: str = "he") -> list[str]:
    # the installer starts the app again when done: in the tray after a quiet update on quit,
    # with the chat open when the player pressed "Update now" (see [Run] in packaging/installer.iss)
    # why an update failed, if it ever does: one log per run (Inno overwrites its log), the last few kept
    logs = USER_KB.parent / "logs"
    for old in sorted(logs.glob("update-*.log"))[:-2] if logs.exists() else []:
        try:
            old.unlink()
        except OSError:
            pass
    log = logs / f"update-{time.strftime('%Y%m%d-%H%M%S')}.log"
    # "Update now": /SILENT shows the installer's own progress window while the app is closed, so the
    # player sees the update happen; an update on quit stays fully quiet (/VERYSILENT)
    # "Update now" keeps Inno's message boxes: a file held by an antivirus scan then offers Retry, where a
    # suppressed box answers Abort and leaves a half-replaced install
    args = [path, "/SILENT" if reopen else "/VERYSILENT", *([] if reopen else ["/SUPPRESSMSGBOXES"]),
            "/NORESTART", f"/LOG={log}",
            # the installer's window in the app's language, not Windows' ([Languages] in installer.iss)
            "/LANG=" + ("english" if lang == "en" else "hebrew")]
    if reopen:
        args.append("/LAUNCHARGS=--updated")
    return args


def windows_shutting_down() -> bool:
    """Windows is shutting down or signing out: an installer started now would be killed halfway."""
    if sys.platform != "win32":
        return False
    import ctypes
    SM_SHUTTINGDOWN = 0x2000
    return bool(ctypes.windll.user32.GetSystemMetrics(SM_SHUTTINGDOWN))


def run_installer_silently(path: str, reopen: bool = False, lang: str = "he") -> None:
    """Runs after the app exits; the installer restarts the app when done."""
    import subprocess
    subprocess.Popen(installer_args(path, reopen, lang), close_fds=True,
                     creationflags=0x00000008 | 0x00000200)  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
