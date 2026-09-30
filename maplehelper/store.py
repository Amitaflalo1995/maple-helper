"""Paths, settings, character profiles and conversation history (all local, under %APPDATA%)."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _app_root() -> Path:
    # PyInstaller unpacks bundled files next to the executable
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


APP_ROOT = _app_root()
ASSETS = APP_ROOT / "assets"
BUNDLED_KB = APP_ROOT / "data" / "kb"
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "MapleHelper"
DATA_DIR.mkdir(parents=True, exist_ok=True)
USER_KB = DATA_DIR / "kb"            # knowledge base updates downloaded at runtime
SHOTS_DIR = DATA_DIR / "shots"       # screenshots live only until the answer arrives
HISTORY_DIR = DATA_DIR / "history"
for d in (SHOTS_DIR, HISTORY_DIR):
    d.mkdir(parents=True, exist_ok=True)


def kb_dir() -> Path:
    """The newest knowledge base: a downloaded update wins over the bundled copy."""
    if (USER_KB / "index.json").exists():
        return USER_KB
    return BUNDLED_KB


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- settings

DEFAULT_SETTINGS = {
    "language": None,             # "he" | "en"; None until onboarding
    "hotkey_toggle": "F9",
    "hotkey_voice": "F10",
    "opacity": 0.85,
    "appearance": "dark",         # dark (black glass, white text) | light (white glass, dark text)
    "font_size": 14,
    "answer_length": "short",     # short | detailed
    "window": None,               # {"x","y","w","h","screen"} saved on move/resize
    "start_with_windows": False,
    "voice_send_immediately": True,
    "microphone": None,
    "model": "sonnet",
    "api_key_fallback": False,    # use an Anthropic API key (stored in Windows Credential Manager)
    "onboarding_done": False,
}


class Settings:
    path = DATA_DIR / "settings.json"

    def __init__(self):
        self.data = {**DEFAULT_SETTINGS, **_read_json(self.path, {})}

    def __getitem__(self, key):
        return self.data.get(key, DEFAULT_SETTINGS.get(key))

    def __setitem__(self, key, value):
        self.data[key] = value
        self.save()

    def save(self):
        _write_json(self.path, self.data)


# ---------------------------------------------------------------- profiles

@dataclass
class Character:
    id: str
    name: str
    base_class: str               # Beginner | Warrior | Magician | Bowman | Thief
    job: str                      # current job, e.g. Fighter, Cleric
    level: int
    map: str = ""
    active_quests: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)

    def summary(self) -> str:
        parts = [f"Name: {self.name}", f"Class: {self.base_class}", f"Job: {self.job}", f"Level: {self.level}"]
        if self.map:
            parts.append(f"Last known map: {self.map}")
        if self.active_quests:
            parts.append("Active quests: " + ", ".join(self.active_quests))
        if self.notes:
            parts.append("Notes: " + "; ".join(self.notes[-10:]))
        return "\n".join(parts)


class Profiles:
    path = DATA_DIR / "profiles.json"

    def __init__(self):
        raw = _read_json(self.path, {"active": None, "characters": []})
        self.characters = [Character(**c) for c in raw.get("characters", [])]
        self.active_id = raw.get("active")

    @property
    def active(self) -> Character | None:
        return next((c for c in self.characters if c.id == self.active_id), None)

    def add(self, name: str, base_class: str, job: str, level: int) -> Character:
        c = Character(id=uuid.uuid4().hex[:8], name=name, base_class=base_class, job=job, level=level)
        self.characters.append(c)
        self.active_id = c.id
        self.save()
        return c

    def set_active(self, cid: str) -> None:
        self.active_id = cid
        self.save()

    def apply_update(self, update: dict) -> list[tuple[str, object]]:
        """Apply a profile update from the assistant. Returns the changed (field, value) pairs."""
        c = self.active
        if not c or not update:
            return []
        changed = []
        for key in ("level", "job", "base_class", "map"):
            val = update.get(key)
            if val in (None, "", 0):
                continue
            if key == "level":
                try:
                    val = int(val)
                except (TypeError, ValueError):
                    continue
                if not 1 <= val <= 250:
                    continue
            if getattr(c, key) != val:
                setattr(c, key, val)
                changed.append((key, val))
        for q in update.get("quests_started", []) or []:
            if q not in c.active_quests:
                c.active_quests.append(q)
                changed.append(("quest+", q))
        for q in update.get("quests_completed", []) or []:
            if q in c.active_quests:
                c.active_quests.remove(q)
                changed.append(("quest-", q))
        note = update.get("note")
        if note and note not in c.notes:
            c.notes.append(note)
            changed.append(("note", note))
        if changed:
            c.updated_at = time.time()
            self.save()
        return changed

    def save(self):
        _write_json(self.path, {"active": self.active_id, "characters": [asdict(c) for c in self.characters]})


# ---------------------------------------------------------------- history

class History:
    """Per-character conversation log (jsonl) plus rolling session summaries."""

    RECENT = 20

    def __init__(self, character_id: str):
        self.log = HISTORY_DIR / f"{character_id}.jsonl"
        self.summaries_path = HISTORY_DIR / f"{character_id}.summaries.json"

    def append(self, role: str, text: str, entities: list[str] | None = None) -> None:
        rec = {"t": time.time(), "role": role, "text": text, "entities": entities or []}
        with self.log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def recent(self, n: int = RECENT) -> list[dict]:
        if not self.log.exists():
            return []
        lines = self.log.read_text(encoding="utf-8").splitlines()[-n:]
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
        return out

    def summaries(self) -> list[str]:
        return _read_json(self.summaries_path, [])

    def add_summary(self, text: str) -> None:
        s = self.summaries()
        s.append(text)
        _write_json(self.summaries_path, s[-10:])

    def clear(self) -> None:
        for p in (self.log, self.summaries_path):
            p.unlink(missing_ok=True)
