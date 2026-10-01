"""What's new in each app version (assets/notes/whatsnew.json, written with every release)."""
from __future__ import annotations

import json

from .store import ASSETS

NOTES = ASSETS / "notes" / "whatsnew.json"
FIRST_TRACKED = "0.3.0"   # installs older than this feature never stored the version they had seen


def version_tuple(v: str) -> tuple[int, ...]:
    out = []
    for part in str(v).split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def load() -> list[dict]:
    """Every version's notes, newest first."""
    try:
        notes = json.loads(NOTES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    notes = [n for n in notes if isinstance(n, dict) and n.get("version")]
    return sorted(notes, key=lambda n: version_tuple(n["version"]), reverse=True)


def since(seen: str, current: str) -> list[dict]:
    """Notes the player hasn't seen: newer than `seen`, up to the running version."""
    lo, hi = version_tuple(seen), version_tuple(current)
    return [n for n in load() if lo < version_tuple(n["version"]) <= hi]
