"""Knowledge-base updates from GitHub Releases (players never hit meowdb.com directly).

A release carries kb-manifest.json: {"version": "2026.10.02", "url": ".../kb.zip", "sha256": "..."}.
The zip is unpacked into %APPDATA%/MapleHelper/kb, which then wins over the bundled copy.
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import urllib.error
import urllib.request
import zipfile

from .store import USER_KB, kb_dir

# Set when the GitHub repository exists (see README, "Publishing").
GITHUB_REPO = ""  # e.g. "owner/maple-helper"
MANIFEST_URL = f"https://github.com/{GITHUB_REPO}/releases/latest/download/kb-manifest.json" if GITHUB_REPO else ""


def local_version() -> str:
    try:
        return json.loads((kb_dir() / "meta.json").read_text(encoding="utf-8")).get("version", "")
    except (OSError, json.JSONDecodeError):
        return ""


def _get(url: str, timeout: int = 30) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MapleHelper"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def update_kb() -> bool:
    """Download a newer knowledge base if one is published. Returns True when updated."""
    if not MANIFEST_URL:
        return False
    raw = _get(MANIFEST_URL, timeout=15)
    if not raw:
        return False
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if manifest.get("version", "") <= local_version():
        return False
    data = _get(manifest["url"], timeout=300)
    if not data or hashlib.sha256(data).hexdigest() != manifest.get("sha256"):
        return False
    tmp = USER_KB.with_name("kb.new")
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(tmp)
    if not (tmp / "index.json").exists():
        shutil.rmtree(tmp, ignore_errors=True)
        return False
    meta_path = tmp / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta["version"] = manifest["version"]
    meta_path.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    shutil.rmtree(USER_KB, ignore_errors=True)
    tmp.rename(USER_KB)
    return True
