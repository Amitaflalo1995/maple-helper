"""Correct display of mixed Hebrew/English text.

Rules (spec, "Hebrew, English and RTL"):
- Every paragraph gets its own direction from its first strong character, not
  from the UI language.
- Inside an RTL paragraph, every English/number run ("Red Snail", "Lv. 10",
  "+5 STR", "10–20%") is wrapped in a left-to-right embedding (LRE…PDF), so it
  behaves as one closed block: brackets, trailing punctuation and signs land
  where a Hebrew reader expects them.
  (Unicode isolates LRI…PDI would be the modern choice, but Qt's text engine
  does not honor them; tests/test_bidi.py measures real glyph positions.)
"""
from __future__ import annotations

import html
import re

LRE, PDF, RLM = "‪", "‬", "‏"  # left-to-right embedding, pop, right-to-left mark
RTL_CHARS = "֐-׿؀-ۿיִ-﷿ﹰ-﻿"
_STRONG = re.compile(rf"[A-Za-z{RTL_CHARS}]")
_RTL = re.compile(rf"[{RTL_CHARS}]")

# An LTR run: starts with a Latin letter, a digit, or a sign followed by a digit;
# may contain spaces and inner punctuation; ends with a letter, digit, % or ).
_RUN = re.compile(
    # start: a letter, a digit, or a sign/$/# right before a digit; but a hyphen glued to a Hebrew
    # letter ("ב-84%", "ל-30") is the Hebrew prefix hyphen, not a minus sign
    rf"(?:(?<![{RTL_CHARS}])[+\-±](?=\d)|[$#](?=\d)|\d|[A-Za-z])"
    # body; "1,500" keeps its comma, a@b.com its @, "11:41" its colon; ": " ends the block
    # ("ה-AI: Claude או Codex" is two blocks, not "AI: Claude" read backwards)
    r"(?:(?:[A-Za-z0-9.'’&/+\-–%#×_ ()@<>]|:(?! )|,(?=\d{3}\b))*"
    r"[A-Za-z0-9%)>])?"                          # "Line 2 <Area 1>" stays one map name
)


def _balanced(run: str) -> str:
    """Trim a run so its brackets are balanced: 'Ellinia (Victoria Road)' stays whole,
    'Lv. 10)' loses the stray ')' and 'Axe Stump (' loses the dangling '('."""
    depth, last_ok = 0, 0
    for i, ch in enumerate(run):
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                break
            depth -= 1
        if depth == 0 and (ch.isalnum() or ch in "%)>"):
            last_ok = i + 1
    return run[:last_ok]


_WORD = re.compile(rf"[A-Za-z{RTL_CHARS}]+")


def direction(text: str) -> str:
    """'rtl' or 'ltr' for one paragraph.

    Starts from the first strong character (Unicode rule P2), but a Hebrew
    sentence that merely opens with an English name ("Red Snail הוא…",
    "(Lv. 10) מפלצת") stays RTL: if at least 40% of its words are Hebrew,
    the paragraph is Hebrew.
    """
    m = _STRONG.search(text)
    if not m:
        return "ltr"
    if _RTL.match(m.group(0)):
        return "rtl"
    words = _WORD.findall(text)
    rtl_words = sum(1 for w in words if _RTL.match(w))
    return "rtl" if words and rtl_words / len(words) >= 0.4 else "ltr"


def isolate_ltr_runs(text: str) -> str:
    """Wrap English/number runs in LRE…PDF. Only for RTL paragraphs."""
    out, pos = [], 0
    for m in _RUN.finditer(text):
        run = _balanced(m.group(0).rstrip(" "))
        start, end = m.start(), m.start() + len(run)
        if not run:
            continue
        out.append(text[pos:start])
        # the RLM after the block keeps following punctuation (") - ", ", ") in the Hebrew flow,
        # so two English blocks never glue into one left-to-right chunk
        # Qt mirrors a ">" that follows a digit inside a Hebrew line ("Line 2 <Area 1>" shows "<Area 1<"),
        # so map names with an <area> suffix are shown as "Line 2 · Area 1"
        shown = re.sub(r"\s*<([^<>]+)>", r" · \1", run)
        out.append(f"{LRE}{shown}{PDF}{RLM}")
        pos = end
    out.append(text[pos:])
    return "".join(out)


def paragraph_html(line: str, d: str | None = None) -> str:
    """One paragraph → HTML with its own dir/alignment; **bold** supported."""
    d = d or direction(line)
    body = isolate_ltr_runs(line) if d == "rtl" else line
    body = html.escape(body)
    body = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", body)
    align = "right" if d == "rtl" else "left"
    return f'<p dir="{d}" align="{align}" style="margin:0 0 4px 0;">{body}</p>'


def paragraph_direction(line: str, message_dir: str) -> str:
    """Inside a Hebrew message, a line is LTR only if it is a real English sentence
    (4+ English words, no Hebrew). "• HP: 371" or "Axe Stump (לבל 17)" stay RTL."""
    if message_dir == "ltr":
        return direction(line)
    if _RTL.search(line):
        return "rtl"
    return "ltr" if len(re.findall(r"[A-Za-z]{2,}", line)) >= 4 and re.search(r"[.?!]\s*$", line) else "rtl"


def message_direction(text: str) -> str:
    """A whole message is Hebrew when a fifth of its words are Hebrew
    (answers are full of English names, so a majority rule would misfire)."""
    words = _WORD.findall(text)
    rtl_words = sum(1 for w in words if _RTL.match(w))
    return "rtl" if words and rtl_words / len(words) >= 0.2 else "ltr"


def to_html(text: str) -> str:
    """Multi-paragraph message → HTML. Blank lines become small gaps; bullets keep their marker."""
    msg_dir = message_direction(text)
    parts = []
    for line in text.strip().split("\n"):
        line = line.rstrip()
        if not line.strip():
            parts.append('<p style="margin:0; font-size:4px;">&nbsp;</p>')
            continue
        line = re.sub(r"^\s*[-*•]\s+", "• ", line)
        parts.append(paragraph_html(line, paragraph_direction(line, msg_dir)))
    return "".join(parts)


def plain(text: str, rtl_ui: bool = False) -> str:
    """For single-line labels (plain text). In a Hebrew UI a label is always RTL
    (an RLM mark fixes its direction even when it starts with an English name)."""
    if rtl_ui or direction(text) == "rtl":
        # RLM on both ends: Qt buttons lay text out LTR regardless of the widget's
        # direction; the trailing mark keeps final punctuation ("?") on the left.
        return RLM + isolate_ltr_runs(text) + RLM
    return text
