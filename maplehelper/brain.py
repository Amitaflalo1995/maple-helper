"""Talks to Claude through the player's own Claude Code install (their Claude account).

Each question runs `claude -p` in a locked-down mode: no shell, no web, no MCP
servers, read-only file tools confined to the knowledge-base folder. The
screenshot travels inside the message itself (stream-json input), so Claude sees
it without an extra tool round-trip, and the answer streams back token by token.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .kb import KnowledgeBase
from .store import Character, History

META = "@@META@@"
CREATE_NO_WINDOW = 0x08000000

SYSTEM_PROMPT = """You are Maple Helper, a personal in-game assistant for MapleStory Classic World (MapleStory Classic), shown as a small chat window on top of the game.

What you receive with each question:
- A screenshot of the game window, taken the moment the player opened the chat (when available).
- The player's character profile, recent conversation, and knowledge-base context the app pre-fetched.

Knowledge base: the current directory is the full NiaMeowDB (meowdb.com) database for MapleStory Classic: index.json (every entity: key, name, category, props) and pages/<category>/<id>.md (full details: stats, drops, maps, quests). Categories: monster, item, map, quest, npc, skill, class, guide, shop, crafting, formula.
- Use the pre-fetched context first. Use Grep/Glob/Read only for what is missing. Never write text before a tool call.
- Never invent facts, numbers, drops or locations. If the data does not say, say so briefly.

Advice must fit the player's level and job. If the profile lacks level or job, ask for it before recommending.

Style:
- Reply in the language of the question (Hebrew or English). Hebrew: natural gamer Hebrew (לגרינד, דרופ, לעשות ג'וב, לבל).
- In-game names (items, monsters, maps, NPCs, skills, quests, jobs) always in English, exactly as in the data.
- {length}
- Plain text with short lines; **bold** allowed; no headings, no tables.

After the answer, output a line containing only @@META@@ followed by one JSON object:
{{"entities": ["monster/5", ...], "profile_update": {{}}, "avatar_box": [0.42, 0.55, 0.05, 0.1]}}
- entities: knowledge-base keys (category/id from index.json) of the main monsters, items, maps, NPCs or quests you mentioned, max 4, most relevant first.
- avatar_box (only with a screenshot, only if clearly visible): [x, y, w, h] as fractions (0-1) of the screenshot, a snug box
  around the PLAYER'S OWN character sprite (find the name tag under it matching the profile name), head to feet, excluding
  the name tag. Omit it if unsure.
- profile_update: only facts the player stated or the screenshot clearly shows: "level" (int), "job", "base_class", "map", "quests_started" [..], "quests_completed" [..], "note" (a lasting preference or goal). Empty object if nothing changed.
"""

LENGTH = {
    "short": "Keep it short: at most 6 short lines unless the player asks for detail.",
    "detailed": "Be thorough but scannable: up to 15 short lines.",
}


def find_claude() -> str | None:
    """Locate the Claude Code executable (native install or npm)."""
    for name in ("claude.exe", "claude"):
        p = shutil.which(name)
        if p and p.lower().endswith(".exe"):
            return p
    candidates = [
        Path(os.environ.get("USERPROFILE", "")) / ".local" / "bin" / "claude.exe",
        Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "claude" / "claude.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return shutil.which("claude")


@dataclass
class Answer:
    text: str = ""
    entities: list[str] = field(default_factory=list)
    profile_update: dict = field(default_factory=dict)
    avatar_box: list | None = None
    error: str | None = None
    cost_usd: float | None = None


REPLY_RULES = """<reply_rules>
- At most {length} short lines. No filler, no follow-up offers.
- Locations, drops and stats only from the context or the knowledge base (Grep pages/monster/*.md for "Map Locations" if needed).
- Then the line @@META@@ and the JSON object. Always include it, even when empty. If the player states a new level/job, put it in profile_update.
</reply_rules>"""
LENGTH_LINES = {"short": 6, "detailed": 15}


def build_prompt(question: str, character: Character | None, history: History | None, kb: KnowledgeBase,
                 has_screenshot: bool, length: str = "short") -> str:
    parts = []
    if character:
        parts.append(f"<player_profile>\n{character.summary()}\n</player_profile>")
    else:
        parts.append("<player_profile>unknown</player_profile>")
    if history:
        summ = history.summaries()
        if summ:
            parts.append("<earlier_sessions>\n" + "\n".join(summ[-3:]) + "\n</earlier_sessions>")
        recent = history.recent()
        if recent:
            convo = "\n".join(f"{'Player' if r['role'] == 'user' else 'Helper'}: {r['text'][:600]}" for r in recent)
            parts.append(f"<recent_conversation>\n{convo}\n</recent_conversation>")
    ctx = []
    if character:
        digest = kb.level_digest(character.level)
        if digest:
            ctx.append(digest)
    for key in kb.find_mentions(question, max_results=4):
        body = kb.page_body(key, limit=2500)
        if body:
            ctx.append(f"[{key}]\n{body}")
    if ctx:
        parts.append("<kb_context>\n" + "\n\n".join(ctx) + "\n</kb_context>")
    parts.append("<screenshot>" + ("attached above" if has_screenshot else "not available") + "</screenshot>")
    parts.append(f"<question>\n{question}\n</question>")
    parts.append(REPLY_RULES.format(length=LENGTH_LINES.get(length, 6)))
    return "\n\n".join(parts)


def split_meta(raw: str) -> tuple[str, dict]:
    """Separate the visible answer from the trailing @@META@@ JSON."""
    if META not in raw:
        return raw.strip(), {}
    text, _, meta = raw.partition(META)
    m = re.search(r"\{.*\}", meta, re.S)
    try:
        return text.strip(), json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return text.strip(), {}


class Brain:
    def __init__(self, kb: KnowledgeBase, model: str = "sonnet", length: str = "short", api_key: str | None = None):
        self.kb = kb
        self.model = model
        self.length = length
        self.api_key = api_key
        self.exe = find_claude()
        self._proc: subprocess.Popen | None = None

    def available(self) -> bool:
        return self.exe is not None

    def cancel(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.kill()

    def ask(self, question: str, character: Character | None, history: History | None,
            screenshot_jpeg: bytes | None, on_delta=None) -> Answer:
        """Blocking call; on_delta(visible_text_so_far) is invoked while the answer streams."""
        if not self.exe:
            return Answer(error="claude_not_installed")
        prompt = build_prompt(question, character, history, self.kb, screenshot_jpeg is not None, self.length)
        content = []
        if screenshot_jpeg:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                         "data": base64.b64encode(screenshot_jpeg).decode()}})
        content.append({"type": "text", "text": prompt})
        msg = {"type": "user", "message": {"role": "user", "content": content}}

        cmd = [self.exe, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               "--include-partial-messages", "--restricted", "--strict-mcp-config", "--tools", "Read,Grep,Glob",
               "--model", self.model, "--no-session-persistence",
               "--system-prompt", SYSTEM_PROMPT.format(length=LENGTH.get(self.length, LENGTH["short"]))]
        env = dict(os.environ)
        if self.api_key:
            env["ANTHROPIC_API_KEY"] = self.api_key
        else:
            env.pop("ANTHROPIC_API_KEY", None)  # use the player's Claude account login
        try:
            self._proc = subprocess.Popen(cmd, cwd=str(self.kb.root), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, env=env, creationflags=CREATE_NO_WINDOW)
        except OSError as e:
            return Answer(error=f"launch_failed: {e}")
        self._proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        self._proc.stdin.close()

        current = ""       # text of the assistant message being streamed
        result = None
        for line in self._proc.stdout:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = ev.get("type")
            if t == "stream_event":
                se = ev.get("event", {})
                if se.get("type") == "message_start":
                    current = ""
                elif se.get("type") == "content_block_delta" and se.get("delta", {}).get("type") == "text_delta":
                    current += se["delta"]["text"]
                    if on_delta:
                        on_delta(current.split(META)[0].strip())
            elif t == "result":
                result = ev
        self._proc.wait()
        stderr = self._proc.stderr.read().decode("utf-8", errors="replace")
        if not result:
            return Answer(error=classify_error(stderr) or "no_result")
        if result.get("is_error"):
            return Answer(error=classify_error(str(result.get("result", "")) + stderr) or "api_error")
        text, meta = split_meta(result.get("result") or current)
        if not meta.get("profile_update"):
            stated = stated_level(question)
            if stated:
                meta.setdefault("profile_update", {})["level"] = stated
        entities = [k for k in meta.get("entities", []) if isinstance(k, str) and kb_has(self.kb, k)]
        if not entities:
            # fallback: cards for the in-game names that appear in the answer itself
            entities = [k for k in self.kb.find_mentions(text, max_results=4)
                        if k.split("/")[0] in ("monster", "item", "npc", "map", "quest")]
        box = meta.get("avatar_box")
        if not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)):
            box = None
        return Answer(text=text, entities=entities[:4], profile_update=meta.get("profile_update") or {},
                      avatar_box=box if screenshot_jpeg else None, cost_usd=result.get("total_cost_usd"))

    def summarize(self, transcript: str) -> str | None:
        """One-paragraph summary of a finished session, kept as long-term context."""
        if not self.exe or not transcript.strip():
            return None
        cmd = [self.exe, "-p", "--restricted", "--strict-mcp-config", "--tools", "", "--model", "haiku",
               "--no-session-persistence", "--system-prompt",
               "Summarize this MapleStory Classic helper conversation in 2-3 sentences for future context: "
               "what the player worked on, decisions, open goals. Same language as the conversation."]
        try:
            r = subprocess.run(cmd, input=transcript.encode("utf-8"), capture_output=True, timeout=90,
                               creationflags=CREATE_NO_WINDOW)
            out = r.stdout.decode("utf-8", errors="replace").strip()
            return out or None
        except (OSError, subprocess.TimeoutExpired):
            return None


_LEVEL_PATTERNS = [
    r"(?:עליתי|הגעתי)\s+(?:ל|ללבל|לרמה)\s*-?\s*(\d{1,3})",
    r"(?:אני|עכשיו)\s+(?:ב)?(?:לבל|רמה)\s*(\d{1,3})",
    r"(?:i'?m|i am|now|reached|hit)\s+(?:level|lvl|lv\.?)\s*(\d{1,3})",
]


def stated_level(text: str) -> int | None:
    """A level the player states about themselves ("עליתי ללבל 16", "I'm level 16")."""
    for pat in _LEVEL_PATTERNS:
        m = re.search(pat, text, re.I)
        if m and 1 <= int(m.group(1)) <= 250:
            return int(m.group(1))
    return None


def kb_has(kb: KnowledgeBase, key: str) -> bool:
    return kb.get(key) is not None


def classify_error(text: str) -> str | None:
    t = text.lower()
    if "not logged in" in t or "please run /login" in t or "invalid api key" in t or "authentication" in t:
        return "not_logged_in"
    if "usage limit" in t or "rate limit" in t or "limit reached" in t or "resets" in t:
        return "usage_limit"
    if "enotfound" in t or "econnrefused" in t or "network" in t or "fetch failed" in t:
        return "offline"
    return None
