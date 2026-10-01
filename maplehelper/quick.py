"""Instant answers straight from the knowledge base, for simple factual questions.

"How much HP does Blue Snail have?", "What does Mano drop?", "Who drops Snail Shell?",
"Where is Red Snail?" are answered in a blink, without Claude (faster, and it saves the
player's plan usage). Anything else, or anything ambiguous, goes to Claude as before,
and every instant answer offers "Ask Claude anyway".
"""
from __future__ import annotations

import re

from .brain import Answer
from .kb import KnowledgeBase

HE = "֐-׿"


def _he(words: str) -> str:
    """Whole Hebrew words: not a letter on either side (so "מי" doesn't match inside another word)."""
    return rf"(?<![{HE}])({words})(?![{HE}])"


# questions that need judgement, the screenshot or the player's situation: always Claude
NEEDS_CLAUDE = re.compile(
    r"\b(why|how|should|best|better|worth|recommend|my|me|i|here|this|that)\b|"
    + _he("למה|איך|כדאי|הכי|עדיף|שווה|מומלץ|שלי|אני|פה|כאן|הזה|הזאת|זה|במסך|תמליץ|לי"), re.I)
DROPS = re.compile(r"\b(drops?|loot)\b|(מפיל|מפילה|מפילים|דרופ|דרופים|נופל)", re.I)
WHO = re.compile(r"\b(who|which (monster|mob)s?)\b|" + _he("מי|מאיפה") + "|איזה מפלצ|איפה משיגים", re.I)
WHERE = re.compile(r"\b(where|location|spawn)\b|(איפה|באיזו מפה|באיזה מפה|מיקום)", re.I)
STATS = [  # (pattern, props key, label); Hebrew as whole words: "לבלו סנייל" (Blue Snail) is not "לבל"
    (re.compile(r"\bhp\b|" + _he("חיים|אייץ' פי"), re.I), "HP", "HP"),
    (re.compile(r"\bmp\b|" + _he("מאנה|מנה"), re.I), "MP", "MP"),
    (re.compile(r"\bexp\b|\bxp\b|" + _he("אקספי|נסיון|ניסיון"), re.I), "EXP", "EXP"),
    (re.compile(r"\blevel\b|\blv\b|" + _he("לבל|רמה"), re.I), "Level", "Level"),
    (re.compile(r"\bdef(ense)?\b|" + _he("הגנה"), re.I), "Defense", "Defense"),
    (re.compile(r"\bacc(uracy)?\b|" + _he("דיוק"), re.I), "Accuracy", "Accuracy"),
    (re.compile(r"\b(att|attack|damage)\b|" + _he("נזק|התקפה"), re.I), "Physical Damage", "Damage"),
]
MAX_WORDS = 9


def answer(question: str, kb: KnowledgeBase, t) -> Answer | None:
    """An Answer from the KB alone, or None when Claude should answer."""
    q = question.strip()
    if not q or len(q.split()) > MAX_WORDS or NEEDS_CLAUDE.search(q):
        return None
    keys = kb.find_mentions(q, max_results=3)
    if len(keys) != 1:
        return None          # nothing named, or several things: a judgement call
    key = keys[0]
    e = kb.get(key) or {}
    cat, name = e.get("category"), e.get("name", key)

    if cat == "item" and (WHO.search(q) or DROPS.search(q)):
        groups = kb.drop_groups([key], limit=6)
        if not groups:
            return None
        return Answer(text=t("quick_who_drops", name=name), entities=[key],
                      drop_groups=groups)
    if cat != "monster":
        return None
    if DROPS.search(q) and not WHO.search(q):
        drops = kb.monster_drops(key)
        if not drops:
            return None
        return Answer(text=t("quick_drops", name=name, n=len(drops)), entities=[key] + drops)
    if WHERE.search(q):
        maps = kb._top_maps(key)
        if not maps:
            return None
        return Answer(text=t("quick_where", name=name) + "\n" + "\n".join(f"• {m}" for m in maps), entities=[key])
    props = e.get("props") or {}
    asked = [(k, label) for rx, k, label in STATS if rx.search(q) and props.get(k) not in (None, "")]
    if asked:
        return Answer(text="\n".join(f"{name} · {label}: {props[k]}" for k, label in asked), entities=[key])
    return None
