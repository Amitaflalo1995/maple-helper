"""Talks to Claude through the player's own Claude Code install (their Claude account).

Each question runs `claude -p` in a locked-down mode: no shell, no web, no MCP
servers, read-only file tools confined to the knowledge-base folder. The
screenshot travels inside the message itself (stream-json input), so Claude sees
it without an extra tool round-trip, and the answer streams back token by token.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from . import usage
from .kb import KnowledgeBase
from .store import Character, History

log = logging.getLogger(__name__)

META = "@@META@@"
REVERSE_WORDS = re.compile(r"(מאיז[הו]|מאילו|איזה|אילו)\s+מפלצ|מי\s+מפיל|which\s+monsters?|who\s+drops|what\s+drops", re.I)
DROP_WORDS = re.compile(r"דרופ|מפיל|נופל|שנופל|drops?\b|loot", re.I)
# no console window flashing up on Windows; elsewhere creationflags must stay 0
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

SYSTEM_PROMPT = """You are Maple Helper, a personal in-game assistant for MapleStory Classic World (MapleStory Classic), shown as a small chat window on top of the game.

What you receive with each question:
- A screenshot of the game window, taken the moment the player opened the chat (when available).
- The player's character profile, recent conversation, and knowledge-base context the app pre-fetched.

Knowledge base: the current directory is the full NiaMeowDB (meowdb.com) database for MapleStory Classic: index.json (every entity: key, name, category, props) and pages/<category>/<id>.md (full details: stats, drops, maps, quests). Categories: monster, item, map, quest, npc, skill, class, guide, shop, crafting, formula.
- Use the pre-fetched context first. Use Grep/Glob/Read only for what is missing. Never write text before a tool call.
- Never invent facts, numbers, drops or locations. If the data does not say, say so briefly.

Which monsters drop something: drops.tsv (monster, level, key, item, item type, item key) lists every monster→item
drop. Grep it for the item name or the item type (e.g. "Throwing Star", "Scroll", "Potion"). Answer grouped per monster
(monster → the items it drops), lowest level first, and return the grouping as META "drop_groups".

Drops: a monster page lists its drops ("Drops (MS Classic)" confirmed by players, and "MSEA reference drops").
When asked what a monster drops, list the drops by name (grouped: Etc / Use / Equipment is fine), say which list they
come from, and return every dropped item's key in entities.

Advice must fit the player's level and job. If the profile lacks level or job, ask for it before recommending.

Style:
- Reply in the language of the question (Hebrew or English). Hebrew: natural gamer Hebrew (לגרינד, דרופ, לעשות ג'וב, לבל).
- In-game names (items, monsters, maps, NPCs, skills, quests, jobs) always in English, exactly as in the data.
- {length}
- Plain text with short lines; **bold** allowed; no headings, no tables.

After the answer, output a line containing only @@META@@ followed by one JSON object:
{{"entities": ["monster/5", ...], "profile_update": {{}}, "avatar_box": [0.42, 0.55, 0.05, 0.1]}}
- entities: knowledge-base keys (category/id from index.json) of what you mention, most relevant first, max 12.
  When the answer is a LIST of items (drops, quest rewards, shop stock, what to buy/equip), include EVERY item's key
  so the app can show each one with its picture. Find keys by grepping index.json for the item names.
- avatar_box (only with a screenshot, only if clearly visible): [x, y, w, h] as fractions (0-1) of the screenshot, a snug box
  around the PLAYER'S OWN character sprite (find the name tag under it matching the profile name), head to feet, excluding
  the name tag. Omit it if unsure.
- drop_groups (only for "which monsters drop X" questions): [{{"monster": "monster/12", "items": ["item/5", ...]}}, ...]
  lowest monster level first, max 8 groups.
- profile_update: only facts the player stated or the screenshot clearly shows: "level" (int), "job", "base_class", "map", "quests_started" [..], "quests_completed" [..], "note" (a lasting preference or goal). Empty object if nothing changed.
"""

LENGTH = {
    "short": "Keep it short: at most 6 short lines unless the player asks for detail.",
    "detailed": "Be thorough but scannable: up to 15 short lines.",
}


def find_claude() -> str | None:
    """Locate the Claude Code executable (native install, npm or Homebrew)."""
    if sys.platform != "win32":
        return _find_claude_posix()
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


# An app opened from Finder gets PATH=/usr/bin:/bin:/usr/sbin:/sbin, so the usual install spots are listed here.
POSIX_CLAUDE_DIRS = ["~/.local/bin", "~/.claude/local", "/opt/homebrew/bin", "/usr/local/bin", "~/.npm-global/bin"]


def _find_claude_posix() -> str | None:
    p = shutil.which("claude")
    if p:
        return p
    for d in POSIX_CLAUDE_DIRS:
        c = Path(d).expanduser() / "claude"
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def child_env(env: dict | None = None) -> dict:
    """Environment for Claude Code: on macOS the install folders join PATH (an npm install needs node)."""
    env = dict(os.environ if env is None else env)
    if sys.platform != "win32":
        extra = [str(Path(d).expanduser()) for d in POSIX_CLAUDE_DIRS]
        env["PATH"] = os.pathsep.join([env.get("PATH") or "/usr/bin:/bin"] + extra)
    return env


@dataclass
class Answer:
    text: str = ""
    entities: list[str] = field(default_factory=list)
    profile_update: dict = field(default_factory=dict)
    avatar_box: list | None = None
    drop_groups: list = field(default_factory=list)
    error: str | None = None
    cost_usd: float | None = None
    limits: dict | None = None          # plan usage (usage.parse of Claude Code's rate_limit_event)


REPLY_RULES = """<reply_rules>
- At most {length} short lines. No filler, no follow-up offers.
- NEVER translate game names: items, monsters, maps, NPCs, skills and quests stay in English exactly as in the data
  ("Blue Snail Shell", not "קונכיית חילזון כחול"), even inside a Hebrew sentence.
- Locations, drops and stats only from the context or the knowledge base (Grep pages/monster/*.md for "Map Locations" if needed).
- Then the line @@META@@ and the JSON object. Always include it, even when empty. If the player states a new level/job, put it in profile_update.
</reply_rules>"""
LENGTH_LINES = {"short": 6, "detailed": 15}


def build_prompt(question: str, character: Character | None, history: History | None, kb: KnowledgeBase,
                 has_screenshot: bool, length: str = "short", focus=None) -> str:
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
    tagged = [k for k in ([focus] if isinstance(focus, str) else (focus or [])) if k and kb.get(k)]
    if tagged:
        names = ", ".join(f"{kb.get(k)['name']} [{k}]" for k in tagged)
        sel = [f"The player tagged these cards; the question is about them unless they say otherwise: {names}"]
        per = 4000 if len(tagged) == 1 else 2000
        for k in tagged:
            sel.append(f"[{k}]\n{kb.page_body(k, limit=per)}")
            if k.startswith("monster/"):
                sel.append(kb.drops_digest(k))
        ctx.append("<selected>\n" + "\n".join(x for x in sel if x) + "\n</selected>")
    if REVERSE_WORDS.search(question):
        items = item_keys_for_question(question, kb)
        groups = kb.drop_groups(items, limit=10)
        if groups:
            lines = ["Which monsters drop it (from drops.tsv; lowest level first; names and keys as in game):"]
            for g in groups:
                m = kb.get(g["monster"])
                lv = (m.get("props") or {}).get("Level", "?")
                lines.append(f"- {m['name']} (Lv {lv}) [{g['monster']}]: "
                             + ", ".join(f"{kb.get(i)['name']} [{i}]" for i in g["items"]))
            ctx.append("\n".join(lines))
    for key in kb.find_mentions(question, max_results=4):
        body = kb.page_body(key, limit=2500)
        if body:
            ctx.append(f"[{key}]\n{body}")
        if key.startswith("monster/"):
            drops = kb.drops_digest(key)
            if drops:
                ctx.append(drops)
    if ctx:
        parts.append("<kb_context>\n" + "\n\n".join(ctx) + "\n</kb_context>")
    parts.append("<screenshot>" + ("attached above" if has_screenshot else "not available") + "</screenshot>")
    parts.append(f"<question>\n{question}\n</question>")
    parts.append(REPLY_RULES.format(length=LENGTH_LINES.get(length, 6)))
    return "\n\n".join(parts)


# Hebrew (and English) words for item families → the item "type" text in the database
ITEM_FAMILIES = [
    (r"כוכב|שוריקן|throwing\s*star|stars?\b", "Throwing Star"),
    (r"חיצ(ים|י)|arrows?\b", "Arrow"),
    (r"שיקוי|שיקויים|פוטיון|potions?\b", "Potion"),
    (r"מגיל(ה|ות)|סקרול|scrolls?\b", "Scroll"),
    (r"כפפ(ה|ות)|gloves?\b", "Glove"),
    (r"נעל(יים)?|boots?|shoes?\b", "Shoes"),
    (r"כוב(ע|עים)|hats?\b|helm", "Hat"),
    (r"מגן|shields?\b", "Shield"),
    (r"עגיל|earrings?\b", "Earring"),
    (r"גלימ(ה|ות)|capes?\b", "Cape"),
]


def item_keys_for_question(question: str, kb: KnowledgeBase) -> list[str]:
    """Items a 'which monsters drop …' question is about: named items, or a whole item family."""
    named = [k for k in kb.find_mentions(question, 12) if k.startswith("item/")]
    if named:
        return named
    for pattern, family in ITEM_FAMILIES:
        if re.search(pattern, question, re.I):
            return [k for k, e in kb.entities.items()
                    if e["category"] == "item" and family.lower() in (e.get("type") or "").lower()]
    return []


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
        self._warm: subprocess.Popen | None = None
        self._warm_config: tuple | None = None
        self._warm_lock = threading.Lock()

    # ------------------------------------------------------------ warm process
    # Claude Code needs ~3s to start. A process started ahead of time sits waiting for its first
    # stdin message, so a question skips that startup entirely. One fresh process per question
    # keeps every answer's context clean.

    def _config(self) -> tuple:
        return (self.exe, self.model, self.length, self.api_key, str(self.kb.root))

    def _spawn(self) -> subprocess.Popen:
        cmd = [self.exe, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               "--include-partial-messages", "--restricted", "--strict-mcp-config", "--tools", "Read,Grep,Glob",
               "--model", self.model, "--no-session-persistence",
               "--system-prompt", SYSTEM_PROMPT.format(length=LENGTH.get(self.length, LENGTH["short"]))]
        env = child_env()
        if self.api_key:
            env["ANTHROPIC_API_KEY"] = self.api_key
        else:
            env.pop("ANTHROPIC_API_KEY", None)  # use the player's Claude account login
        return subprocess.Popen(cmd, cwd=str(self.kb.root), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, creationflags=CREATE_NO_WINDOW)

    def prewarm(self) -> None:
        """Start the next question's process now (no-op if one is ready)."""
        if not self.exe:
            return
        with self._warm_lock:
            if self._warm and self._warm.poll() is None and self._warm_config == self._config():
                return
            self._discard_warm()
            try:
                self._warm, self._warm_config = self._spawn(), self._config()
            except OSError:
                self._warm = None

    def _take_warm(self) -> subprocess.Popen | None:
        with self._warm_lock:
            p, cfg = self._warm, self._warm_config
            self._warm = None
        if p and p.poll() is None and cfg == self._config():
            return p
        if p and p.poll() is None:
            p.kill()
        return None

    def _discard_warm(self) -> None:
        if self._warm and self._warm.poll() is None:
            self._warm.kill()
        self._warm = None

    def shutdown(self) -> None:
        with self._warm_lock:
            self._discard_warm()
        self.cancel()

    def available(self) -> bool:
        return self.exe is not None

    def cancel(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.kill()

    def ask(self, question: str, character: Character | None, history: History | None,
            screenshot_jpeg: bytes | None, on_delta=None, focus=None) -> Answer:
        """Blocking call; on_delta(visible_text_so_far) is invoked while the answer streams."""
        if not self.exe:
            return Answer(error="claude_not_installed")
        self.kb.ensure_drop_table()
        prompt = build_prompt(question, character, history, self.kb, screenshot_jpeg is not None, self.length, focus)
        content = []
        if screenshot_jpeg:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                         "data": base64.b64encode(screenshot_jpeg).decode()}})
        content.append({"type": "text", "text": prompt})
        msg = {"type": "user", "message": {"role": "user", "content": content}}

        try:
            self._proc = self._take_warm() or self._spawn()
        except OSError as e:
            log.error("could not start Claude Code: %s", e)
            return Answer(error=f"launch_failed: {e}")
        try:
            self._proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
            self._proc.stdin.close()
        except OSError:
            # the warm process died meanwhile: start fresh once
            self._proc = self._spawn()
            self._proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
            self._proc.stdin.close()
        # get the next one ready while the player reads this answer
        threading.Thread(target=self.prewarm, daemon=True).start()

        current = ""       # text of the assistant message being streamed
        result = None
        limits = None
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
            elif t == "rate_limit_event":
                limits = usage.parse(ev.get("rate_limit_info"))
        self._proc.wait()
        stderr = self._proc.stderr.read().decode("utf-8", errors="replace")
        if not result:
            if limits:
                return Answer(error=classify_error(stderr) or "no_result", limits=limits)
            log.warning("no result from Claude Code (exit %s): %s", self._proc.returncode, stderr[-1500:])
            return Answer(error=classify_error(stderr) or "no_result")
        if result.get("is_error"):
            log.warning("Claude Code error: %s | %s", str(result.get("result", ""))[:500], stderr[-1000:])
            return Answer(error=classify_error(str(result.get("result", "")) + stderr) or "api_error")
        text, meta = split_meta(result.get("result") or current)
        if not meta.get("profile_update"):
            stated = stated_level(question)
            if stated:
                meta.setdefault("profile_update", {})["level"] = stated
        entities = [k for k in meta.get("entities", []) if isinstance(k, str) and kb_has(self.kb, k)][:12]
        groups = []
        for g in meta.get("drop_groups") or []:
            if isinstance(g, dict) and kb_has(self.kb, str(g.get("monster", ""))):
                items = [i for i in g.get("items") or [] if isinstance(i, str) and kb_has(self.kb, i)]
                if items:
                    groups.append({"monster": g["monster"], "items": items[:10]})
        if REVERSE_WORDS.search(question) and not groups:
            # the app builds the grouping itself: the question's items, else the items the answer names
            items = item_keys_for_question(question, self.kb) or \
                [k for k in entities if k.startswith("item/")] or \
                [k for k in self.kb.find_mentions(text, 12) if k.startswith("item/")]
            groups = self.kb.drop_groups(items)
        if groups:
            entities = []          # the grouped view replaces the flat cards
        elif DROP_WORDS.search(question):
            # a drops question: the monster card + every drop as a tile, straight from the database
            monsters = [k for k in entities if k.startswith("monster/")] or \
                [k for k in self.kb.find_mentions(question, 4) if k.startswith("monster/")]
            if monsters:
                drops = self.kb.monster_drops(monsters[0])
                entities = [monsters[0]] + drops
        if not entities:
            # fallback: cards for the in-game names that appear in the answer itself
            entities = [k for k in self.kb.find_mentions(text, max_results=12)
                        if k.split("/")[0] in ("monster", "item", "npc", "map", "quest")]
        box = meta.get("avatar_box")
        if not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)):
            box = None
        return Answer(text=text, entities=entities[:12], drop_groups=groups[:8], profile_update=meta.get("profile_update") or {},
                      avatar_box=box if screenshot_jpeg else None, cost_usd=result.get("total_cost_usd"),
                      limits=limits)

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
                               env=child_env(), creationflags=CREATE_NO_WINDOW)
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
