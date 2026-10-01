"""Asks the player's chosen AI (Claude Code or Codex, see providers/) and turns its reply into an Answer.

The prompt, the knowledge-base pre-fetch and the answer post-processing (cards,
drop groups, profile updates) live here and are the same for every provider;
the provider's backend only runs the CLI and returns the raw text.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from . import providers
from .kb import KnowledgeBase
from .store import Character, History

log = logging.getLogger(__name__)

META = "@@META@@"
REVERSE_WORDS = re.compile(r"(מאיז[הו]|מאילו|איזה|אילו)\s+מפלצ|מי\s+מפיל|which\s+monsters?|who\s+drops|what\s+drops", re.I)
DROP_WORDS = re.compile(r"דרופ|מפיל|נופל|שנופל|drops?\b|loot", re.I)
SUMMARY_PROMPT = ("Summarize this MapleStory Classic helper conversation in 2-3 sentences for future context: "
                  "what the player worked on, decisions, open goals. Same language as the conversation.")

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
- profile_update: only facts the player stated or the screenshot clearly shows: "level" (int), "job", "base_class", "map", "quests_started" [..], "quests_completed" [..], "exp_percent" (number 0-100, the EXP bar's percentage, only if the screenshot shows it), "stats" (only if the in-game stat window is open in the screenshot: {{"acc": total Accuracy, "dmg_min": and "dmg_max": the attack/damage range it shows, "hp": max HP, "mp": max MP}}), "note" (a lasting preference or goal). Empty object if nothing changed.
"""

LENGTH = {
    "short": "Keep it short: at most 6 short lines unless the player asks for detail.",
    "detailed": "Be thorough but scannable: up to 15 short lines.",
}


@dataclass
class Answer:
    text: str = ""
    entities: list[str] = field(default_factory=list)
    profile_update: dict = field(default_factory=dict)
    avatar_box: list | None = None
    drop_groups: list = field(default_factory=list)
    error: str | None = None
    cost_usd: float | None = None
    limits: dict | None = None          # Claude plan usage (usage.parse of Claude Code's rate_limit_event)
    model: str | None = None            # the model that answered, when the CLI says


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
    def __init__(self, kb: KnowledgeBase, provider: str = providers.DEFAULT, model: str | None = None,
                 length: str = "short", api_key: str | None = None):
        self.kb = kb
        self.model = model
        self.length = length
        self.api_key = api_key
        self._provider = providers.get(provider)
        self.backend = self._provider.backend(self)

    @property
    def provider(self) -> str:
        return self._provider.name

    @provider.setter
    def provider(self, name: str) -> None:
        """Switch AI: the old backend's processes are stopped, the new one starts cold."""
        new = providers.get(name)
        if new.name != self._provider.name:
            self.backend.shutdown()
            self._provider, self.backend = new, new.backend(self)

    def system_prompt(self) -> str:
        return SYSTEM_PROMPT.format(length=LENGTH.get(self.length, LENGTH["short"]))

    def prewarm(self) -> None:
        """Get the next question's process ready now, where the provider supports it."""
        self.backend.prewarm()

    def shutdown(self) -> None:
        self.backend.shutdown()

    def available(self) -> bool:
        return self.backend.exe is not None

    def cancel(self) -> None:
        self.backend.cancel()

    def ask(self, question: str, character: Character | None, history: History | None,
            screenshot_jpeg: bytes | None, on_delta=None, focus=None) -> Answer:
        """Blocking call; on_delta(visible_text_so_far) is invoked while the answer streams."""
        if not self.backend.exe:
            return Answer(error="not_installed")
        self.kb.ensure_drop_table()
        prompt = build_prompt(question, character, history, self.kb, screenshot_jpeg is not None, self.length, focus)
        raw_delta = (lambda raw: on_delta(raw.split(META)[0].strip())) if on_delta else None
        result = self.backend.run(prompt, screenshot_jpeg, raw_delta)
        if result.error:
            return Answer(error=result.error, limits=result.limits)
        text, meta = split_meta(result.text)
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
                      avatar_box=box if screenshot_jpeg else None, cost_usd=result.cost_usd,
                      limits=result.limits, model=result.model)

    def summarize(self, transcript: str) -> str | None:
        """One-paragraph summary of a finished session, kept as long-term context."""
        if not transcript.strip():
            return None
        return self.backend.summarize(SUMMARY_PROMPT, transcript)

    def summarize_guide(self, key: str, page: str, lang: str) -> str | None:
        """The practical takeaways of a KB guide in the player's language (a light model, one short call)."""
        language = "Hebrew" if lang == "he" else "English"
        prompt = (f"Summarize this MapleStory Classic guide for a player, in {language}: 6-10 short bullet lines "
                  "('• ...') with the most useful practical advice (builds, levels, where to go, what to buy). "
                  "Keep every game name (items, monsters, maps, skills, jobs) in English exactly as written. "
                  "No intro, no outro.")
        out = self.backend.summarize(prompt, page[:60000], timeout=120)
        if not out:
            log.warning("guide summary failed for %s", key)
        return out


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
