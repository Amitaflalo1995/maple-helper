"""Build data/kb/aliases.json: Hebrew names and transliterations Israeli players use for
monsters, maps, towns and NPCs, so "חילזון אדום" or "רד סנייל" resolve to Red Snail.

Generated with Claude Code in batches, then merged. Re-running only fills what's missing.

Usage: python tools/make_aliases.py monster map npc
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KB = ROOT / "data" / "kb"
OUT = KB / "aliases.json"
BATCH = 80

PROMPT = """You map MapleStory Classic names to the Hebrew names Israeli players type or say.
For each entry return 2-4 Hebrew aliases. ALWAYS include the phonetic Hebrew transliteration of the English
name as players say it ("רד סנייל", "דארק לורד", "הנסיס"), plus common spelling variants ("הניסיס"),
and a Hebrew translation only when players actually use one ("חילזון אדום").
Skip generic words that would cause false matches (e.g. do not alias a monster as just "עץ").
Return ONLY a JSON object: {"<key>": ["alias", ...], ...} with exactly the keys given.

Entries (key | English name):
"""


def claude_exe() -> str:
    sys.path.insert(0, str(ROOT))
    from maplehelper.brain import find_claude
    exe = find_claude()
    if not exe:
        sys.exit("Claude Code not found")
    return exe


def ask(exe: str, rows: list[tuple[str, str]]) -> dict:
    text = PROMPT + "\n".join(f"{k} | {n}" for k, n in rows)
    r = subprocess.run([exe, "-p", "--restricted", "--strict-mcp-config", "--tools", "", "--model", "sonnet",
                        "--no-session-persistence"], input=text.encode("utf-8"), capture_output=True, timeout=600)
    out = r.stdout.decode("utf-8", errors="replace")
    m = re.search(r"\{.*\}", out, re.S)
    return json.loads(m.group(0)) if m else {}


def main(categories: list[str]):
    index = json.loads((KB / "index.json").read_text(encoding="utf-8"))
    aliases = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    exe = claude_exe()
    seen_names = set()
    rows = []
    for e in index:
        if e["category"] in categories and e["key"] not in aliases:
            name = e["name"]
            if name.lower() in seen_names or re.search(r"\(alt\)|\bPQ\b|\(KPQ\)", name):
                continue  # one entry per display name; skip party-quest variants
            seen_names.add(name.lower())
            rows.append((e["key"], name))
    print(f"{len(rows)} names to alias")
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        try:
            got = ask(exe, batch)
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as ex:
            print("batch failed:", ex)
            continue
        valid = {k: [a for a in v if isinstance(a, str) and re.search(r"[֐-׿]", a)]
                 for k, v in got.items() if k in dict(batch)}
        aliases.update({k: v for k, v in valid.items() if v})
        OUT.write_text(json.dumps(aliases, ensure_ascii=False, indent=0), encoding="utf-8")
        print(f"  {min(i + BATCH, len(rows))}/{len(rows)}")
    print(f"aliases.json: {len(aliases)} entries")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1:] or ["monster"])
