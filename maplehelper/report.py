"""Diagnostics: a rotating log file, and a one-click problem report for players to send.

The report holds what helps fix a bug (log, version, settings, system) and nothing private:
no conversations, no screenshots, no characters, no API key, no email.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import platform
import sys
import threading
import time
import zipfile
from pathlib import Path

from .store import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "maplehelper.log"
PRIVATE_SETTINGS = ("window", "bubble_pos")
log = logging.getLogger("maplehelper")


def setup_logging() -> None:
    """Log to %APPDATA%/MapleHelper/logs (3 x 1 MB), including crashes on any thread."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)
    root.setLevel(logging.INFO)

    def on_crash(exc_type, exc, tb):
        log.critical("uncaught exception", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)
    sys.excepthook = on_crash
    threading.excepthook = lambda a: log.critical(f"uncaught exception in thread {a.thread and a.thread.name}",
                                                  exc_info=(a.exc_type, a.exc_value, a.exc_traceback))


def system_info(version: str, kb_version: str, claude_status: str) -> dict:
    return {"app_version": version, "kb_version": kb_version, "claude": claude_status,
            "windows": platform.platform(), "python": sys.version.split()[0],
            "frozen": bool(getattr(sys, "frozen", False)), "created": time.strftime("%Y-%m-%d %H:%M:%S")}


def build_report(out_dir: Path, info: dict, settings: dict) -> Path:
    """Zip the logs + info + settings (minus private bits) into out_dir; returns the zip path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"MapleHelper-report-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    clean = {k: v for k, v in settings.items() if k not in PRIVATE_SETTINGS}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("info.json", json.dumps(info, ensure_ascii=False, indent=1))
        z.writestr("settings.json", json.dumps(clean, ensure_ascii=False, indent=1))
        for f in sorted(LOG_DIR.glob("maplehelper.log*")):
            z.write(f, f"logs/{f.name}")
    return path
