"""Claude plan usage, as Claude Code reports it after every answer (rate_limit_event).

The numbers are the player's whole plan (the 5-hour and weekly windows), including Claude use
outside Maple Helper. They drive the usage meter in Settings, a heads-up in the chat when the
5-hour window runs low, and the saver mode suggestion.
"""
from __future__ import annotations

import time

WINDOWS = ("five_hour", "seven_day")
HIGH = 0.8        # suggest saver mode
CRITICAL = 0.95   # warn that answers may stop until the reset
SAVER_MODEL = "haiku"


def parse(info: dict | None) -> dict | None:
    """{"five_hour": {"used": 0.7, "resets": 1790845200}, "seven_day": {...}} from a rate_limit_info."""
    if not isinstance(info, dict):
        return None
    windows = info.get("unifiedWindows") or {}
    out = {}
    for name in WINDOWS:
        w = windows.get(name)
        if isinstance(w, dict) and isinstance(w.get("utilization"), (int, float)):
            out[name] = {"used": float(w["utilization"]), "resets": w.get("resetsAt")}
    if not out and info.get("rateLimitType") in WINDOWS and isinstance(info.get("utilization"), (int, float)):
        out[info["rateLimitType"]] = {"used": float(info["utilization"]), "resets": info.get("resetsAt")}
    return out or None


def record(settings, limits: dict | None, now: float | None = None) -> None:
    if limits:
        settings["usage"] = {**limits, "seen": now if now is not None else time.time()}


def current(settings, now: float | None = None) -> dict:
    """The last known usage, minus windows that have reset since (their usage is back to zero)."""
    now = now if now is not None else time.time()
    u = settings["usage"] or {}
    return {k: v for k, v in u.items() if k in WINDOWS and not (v.get("resets") and v["resets"] <= now)}


def level(settings, now: float | None = None) -> str:
    """'ok' | 'high' | 'critical', from the 5-hour window (the one that runs out during play)."""
    used = current(settings, now).get("five_hour", {}).get("used", 0.0)
    return "critical" if used >= CRITICAL else "high" if used >= HIGH else "ok"


def reset_clock(resets: float | None) -> str:
    return time.strftime("%H:%M", time.localtime(resets)) if resets else ""


def lines(settings, t, now: float | None = None) -> list[str]:
    """Readable meter lines for Settings (t = I18n)."""
    u = current(settings, now)
    out = []
    if "five_hour" in u:
        w = u["five_hour"]
        out.append(t("usage_5h", pct=round(w["used"] * 100), at=reset_clock(w.get("resets"))))
    if "seven_day" in u:
        out.append(t("usage_week", pct=round(u["seven_day"]["used"] * 100)))
    return out or [t("usage_unknown")]
