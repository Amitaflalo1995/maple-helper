"""Play timers: buffs, potions, a boss respawn. They only count time and tell the player when it's up;
nothing touches the game. Presets are kept in the settings ("timer_presets")."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

DEFAULT_PRESETS = [{"name": "Buff", "seconds": 200}, {"name": "Potions", "seconds": 600},
                   {"name": "Boss", "seconds": 2700}]
MAX_RUNNING = 6


@dataclass
class Running:
    id: str
    name: str
    seconds: int
    ends: float

    def left(self, now: float | None = None) -> int:
        return max(0, round(self.ends - (now if now is not None else time.time())))


def clock(seconds: int) -> str:
    """125 -> "2:05", 3725 -> "1:02:05"."""
    h, rest = divmod(max(0, int(seconds)), 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def parse_clock(text: str) -> int | None:
    """"3" -> 180 (minutes), "2:30" -> 150, "1:00:00" -> 3600; None if it isn't a time."""
    parts = text.strip().split(":")
    if not all(p.strip().isdigit() for p in parts) or not 1 <= len(parts) <= 3:
        return None
    nums = [int(p) for p in parts]
    if len(nums) == 1:
        return nums[0] * 60 or None
    secs = 0
    for n in nums:
        secs = secs * 60 + n
    return secs or None


class Timers(QObject):
    """The running timers. `changed` every second while any runs; `finished(name)` when one is up."""
    changed = Signal()
    finished = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.running: list[Running] = []
        self._tick = QTimer(self, interval=1000)
        self._tick.timeout.connect(self._on_tick)

    def start(self, name: str, seconds: int) -> Running:
        """Start (or restart, by name) a timer."""
        self.running = [r for r in self.running if r.name != name]
        r = Running(uuid.uuid4().hex[:6], name, int(seconds), time.time() + int(seconds))
        self.running.append(r)
        self.running = self.running[-MAX_RUNNING:]
        self._tick.start()
        self.changed.emit()
        return r

    def restart(self, rid: str):
        r = next((r for r in self.running if r.id == rid), None)
        if r:
            self.start(r.name, r.seconds)

    def stop(self, rid: str):
        self.running = [r for r in self.running if r.id != rid]
        if not self.running:
            self._tick.stop()
        self.changed.emit()

    def _on_tick(self):
        now = time.time()
        for r in [r for r in self.running if r.left(now) == 0 and r.ends > 0]:
            r.ends = 0                      # stays on the bar as "done" until restarted or closed
            self.finished.emit(r.name)
        self.changed.emit()
