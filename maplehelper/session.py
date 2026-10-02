"""What happened in a play session, for the "last session" summary shown when the chat next opens."""
from __future__ import annotations

import time


class SessionStats:
    """Per character: level and job at the start, questions asked, quests started and completed."""

    def __init__(self, now: float | None = None):
        self.started = now if now is not None else time.time()
        self.last_active = self.started
        self.chars: dict[str, dict] = {}

    def _entry(self, c) -> dict:
        return self.chars.setdefault(c.id, {"name": c.name, "start_level": c.level, "start_job": c.job,
                                            "questions": 0, "quests_done": [], "quests_started": []})

    def touch(self, c) -> None:
        if c:
            self._entry(c)

    def question(self, c, now: float | None = None) -> None:
        self.last_active = now if now is not None else time.time()
        if c:
            self._entry(c)["questions"] += 1

    def change(self, c, field: str, value) -> None:
        if not c:
            return
        e = self._entry(c)
        if field == "quest-" and value not in e["quests_done"]:
            e["quests_done"].append(value)
        elif field == "quest+" and value not in e["quests_started"]:
            e["quests_started"].append(value)

    def summary(self, profiles) -> dict | None:
        """None when nothing worth showing happened."""
        rows = []
        for cid, e in self.chars.items():
            c = next((c for c in profiles.characters if c.id == cid), None)
            if not c:
                continue
            row = {**e, "id": cid, "name": c.name, "end_level": c.level, "end_job": c.job}
            if row["questions"] or row["quests_done"] or row["quests_started"] or c.level != e["start_level"]:
                rows.append(row)
        if not rows:
            return None
        minutes = max(1, round((self.last_active - self.started) / 60))
        return {"ended": time.strftime("%Y-%m-%d %H:%M"), "minutes": minutes, "chars": rows,
                "from": self.started, "to": self.last_active}


def questions(summary: dict, history_for, limit: int = 30) -> dict[str, list[str]]:
    """The player's own questions in that session, per character name (history_for(id) -> History)."""
    lo, hi = summary.get("from"), summary.get("to")
    out: dict[str, list[str]] = {}
    if lo is None or hi is None:
        return out
    for r in summary["chars"]:
        if not r.get("id"):
            continue
        asked = [m["text"] for m in history_for(r["id"]).recent(400)
                 if m.get("role") == "user" and lo - 1 <= m.get("t", 0) <= hi + 1]
        if asked:
            out[r["name"]] = asked[-limit:]
    return out


def lines(summary: dict, t) -> list[str]:
    """Readable lines for one summary (t = I18n). An empty line separates one character from the next; in Hebrew
    every English name (a character, a quest) is one left-to-right block, or its brackets and order broke."""
    from . import bidi
    rtl = getattr(t, "rtl", False)
    out = []
    for i, r in enumerate(summary["chars"]):
        if i:
            out.append("")
        name = bidi.name_block(r["name"], rtl)       # a Hebrew name in an English line is one block too
        if r["end_level"] != r["start_level"]:
            out.append(t("sess_level", name=name, a=r["start_level"], b=r["end_level"]))
        else:
            out.append(t("sess_char", name=name, level=r["end_level"]))
        if r["end_job"] != r["start_job"]:
            out.append(t("sess_job", job=r["end_job"]))
        if r["quests_done"]:
            names = (bidi.RLM + ", ").join(bidi.ltr_block(q, rtl) for q in r["quests_done"][:4])
            out.append(t("sess_quests_done", n=len(r["quests_done"]), names=names))
        if r["quests_started"]:
            out.append(t("sess_quests_started", n=len(r["quests_started"])))
        if r["questions"]:
            out.append(t("sess_questions", n=r["questions"]))
    return out
