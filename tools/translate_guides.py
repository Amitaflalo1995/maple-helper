"""Translation round-trip for the guides built by tools/build_guides.py.

  export <lang> <out_dir>   writes <out_dir>/<slug>.json = {"strings": {id: English}} for every guide whose
                            translation is missing or stale (only the strings that need translating)
  import <lang> <in_dir>    reads <in_dir>/<slug>.json = {id: translation} and writes
                            assets/guides/<lang>/<slug>.json (same blocks, translated text, source_hash)

Strings without letters (numbers, "-") are kept as they are and never exported.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDES = ROOT / "assets" / "guides"
_ICON = re.compile(r"\[\[img:[^\]]+\]\]")
TEXT_KEYS = ("h2", "h3", "p", "note", "ul", "ol", "table", "cap", "text")


def needs_words(s: str) -> bool:
    return bool(re.search(r"[A-Za-z]", _ICON.sub("", s)))


def strings(guide: dict) -> list[str]:
    """Every translatable string of a guide, in reading order."""
    out = [guide.get("title", ""), guide.get("intro", "")]
    for b in guide.get("blocks", []):
        for k in TEXT_KEYS:
            v = b.get(k)
            if isinstance(v, str):
                out.append(v)
            elif k == "table" and v:
                out += [c for row in v for c in row]
            elif isinstance(v, list):
                out += v
    return [s for s in out if s and needs_words(s)]


def translate(guide: dict, tr: dict[str, str]) -> dict:
    """The guide with every string replaced by its translation (missing ones stay English)."""
    def t(s):
        return tr.get(s, s) if isinstance(s, str) else s
    blocks = []
    for b in guide.get("blocks", []):
        nb = dict(b)
        for k in TEXT_KEYS:
            v = b.get(k)
            if isinstance(v, str):
                nb[k] = t(v)
            elif k == "table" and v:
                nb[k] = [[t(c) for c in row] for row in v]
            elif isinstance(v, list):
                nb[k] = [t(x) for x in v]
        blocks.append(nb)
    return {"title": t(guide.get("title", "")), "intro": t(guide.get("intro", "")), "blocks": blocks}


def export(lang: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in sorted((GUIDES / "en").glob("*.json")):
        en = json.loads(f.read_text(encoding="utf-8"))
        cur = GUIDES / lang / f.name
        if cur.exists():
            tr = json.loads(cur.read_text(encoding="utf-8"))
            if tr.get("source_hash") == en.get("hash") and tr.get("blocks"):
                continue
        uniq = list(dict.fromkeys(strings(en)))
        (out_dir / f.name).write_text(json.dumps({"strings": {str(i): s for i, s in enumerate(uniq)}},
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
        print(f.stem, len(uniq))


def import_(lang: str, in_dir: Path) -> None:
    for f in sorted(in_dir.glob("*.json")):
        if f.name.endswith(".src.json"):
            continue
        src = json.loads((in_dir / f.name.replace(".json", ".src.json")).read_text(encoding="utf-8"))["strings"] \
            if (in_dir / f.name.replace(".json", ".src.json")).exists() else None
        done = json.loads(f.read_text(encoding="utf-8"))
        en = json.loads((GUIDES / "en" / f.name).read_text(encoding="utf-8"))
        src = src or {str(i): s for i, s in enumerate(dict.fromkeys(strings(en)))}
        tr = {src[i]: v for i, v in done.items() if i in src and isinstance(v, str) and v.strip()}
        missing = [i for i in src if i not in done]
        out = {**translate(en, tr), "source_hash": en["hash"]}
        (GUIDES / lang).mkdir(exist_ok=True)
        (GUIDES / lang / f.name).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f.stem, f"{len(tr)} translated", f"{len(missing)} missing" if missing else "")


if __name__ == "__main__":
    cmd, lang, folder = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    export(lang, folder) if cmd == "export" else import_(lang, folder)
