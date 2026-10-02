"""Plan usage: Claude's as Claude Code reports it after every answer (rate_limit_event),
ChatGPT's as the Codex CLI reports it when asked (app-server account/rateLimits/read).

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
    windows = info.get("unifiedWindows")
    windows = windows if isinstance(windows, dict) else {}      # outside data: never trust its shape
    out = {}
    for name in WINDOWS:
        w = windows.get(name)
        if isinstance(w, dict) and isinstance(w.get("utilization"), (int, float)):
            out[name] = {"used": float(w["utilization"]), "resets": w.get("resetsAt")}
    if not out and info.get("rateLimitType") in WINDOWS and isinstance(info.get("utilization"), (int, float)):
        out[info["rateLimitType"]] = {"used": float(info["utilization"]), "resets": info.get("resetsAt")}
    return out or None


def parse_codex(snapshot: dict | None) -> dict | None:
    """Same shape as parse(), from a Codex rate-limit snapshot ({"primary": {"usedPercent": 17,
    "windowDurationMins": 300, "resetsAt": ...}, "secondary": {...}}); windows go by their length."""
    if not isinstance(snapshot, dict):
        return None
    out = {}
    for slot, fallback in (("primary", "five_hour"), ("secondary", "seven_day")):
        w = snapshot.get(slot)
        if not isinstance(w, dict) or not isinstance(w.get("usedPercent"), (int, float)):
            continue
        mins = w.get("windowDurationMins")
        name = fallback if not mins else "five_hour" if mins <= 6 * 60 else "seven_day" if mins >= 6 * 24 * 60 else None
        if name and name not in out:
            out[name] = {"used": float(w["usedPercent"]) / 100, "resets": w.get("resetsAt")}
    return out or None


def record(settings, limits: dict | None, now: float | None = None, provider: str = "claude") -> None:
    if limits:
        settings["usage"] = {**limits, "seen": now if now is not None else time.time(), "provider": provider}


def current(settings, now: float | None = None, provider: str | None = None) -> dict:
    """The last known usage, minus windows that have reset since (their usage is back to zero).
    With a provider: only that provider's numbers (Claude's plan says nothing about ChatGPT's)."""
    now = now if now is not None else time.time()
    u = settings["usage"] or {}
    if provider and u.get("provider", "claude") != provider:
        return {}
    def live(v) -> bool:
        r = v.get("resets") if isinstance(v, dict) else None
        return isinstance(v, dict) and isinstance(v.get("used"), (int, float)) and \
            not (isinstance(r, (int, float)) and r <= now)
    return {k: v for k, v in u.items() if k in WINDOWS and live(v)}


def level(settings, now: float | None = None, provider: str | None = None) -> str:
    """'ok' | 'high' | 'critical', from the 5-hour window (the one that runs out during play)."""
    used = current(settings, now, provider).get("five_hour", {}).get("used", 0.0)
    return "critical" if used >= CRITICAL else "high" if used >= HIGH else "ok"


def reset_clock(resets: float | None) -> str:
    return time.strftime("%H:%M", time.localtime(resets)) if isinstance(resets, (int, float)) and resets else ""


def lines(settings, t, now: float | None = None, provider: str = "claude") -> list[str]:
    """Readable meter lines for Settings (t = I18n)."""
    u = current(settings, now, provider)
    out = []
    if "five_hour" in u:
        pct, at = round(u["five_hour"]["used"] * 100), reset_clock(u["five_hour"].get("resets"))
        out.append(t("usage_5h", pct=pct, at=at) if at else t("usage_5h_only", pct=pct))
    if "seven_day" in u:
        out.append(t("usage_week", pct=round(u["seven_day"]["used"] * 100)))
    return out or [t.p("usage_unknown", provider)]
