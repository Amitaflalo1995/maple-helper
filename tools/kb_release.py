"""Knowledge-base checks and packing used by CI (and by hand).

    python tools/kb_release.py validate data/kb [--previous old/index.json] [--min-entities N]
    python tools/kb_release.py pack data/kb dist-kb [--version 2026.10.02.1200]

`validate` is the gate in front of every KB publish: a broken scrape must never reach players.
`pack` writes kb.zip + kb-manifest.json in the format maplehelper/updater.py reads (the same
format tools/release.py writes): {"version", "sha256", "url": ".../releases/latest/download/kb.zip"}.
Versions are zero-padded UTC timestamps, so plain string comparison orders them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import zipfile
from pathlib import Path

REPO = "Amitaflalo1995/maple-helper"
CATEGORIES = ["monster", "item", "map", "quest", "npc", "skill", "class", "guide", "shop", "crafting", "formula"]
MIN_KEEP_RATIO = 0.9   # an update may not lose more than 10% of the previous entities


class InvalidKB(Exception):
    pass


def validate(kb: Path, previous_index: Path | None = None, min_entities: int = 1,
             categories: list[str] = CATEGORIES) -> dict:
    """Raise InvalidKB listing every problem found; return a small summary when the KB is usable."""
    problems: list[str] = []
    try:
        index = json.loads((kb / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise InvalidKB(f"index.json unreadable: {e}") from e
    if not isinstance(index, list):
        raise InvalidKB("index.json is not a list")

    count = len(index)
    if count < min_entities:
        problems.append(f"only {count} entities (minimum {min_entities})")
    if previous_index and previous_index.exists():
        prev = len(json.loads(previous_index.read_text(encoding="utf-8")))
        if count < prev * MIN_KEEP_RATIO:
            problems.append(f"{count} entities, down from {prev} (more than {100 - MIN_KEEP_RATIO * 100:.0f}% lost)")

    seen = {e.get("category") for e in index if isinstance(e, dict)}
    missing_cats = [c for c in categories if c not in seen]
    if missing_cats:
        problems.append("missing categories: " + ", ".join(missing_cats))

    missing_pages = []
    for e in index:
        key = e.get("key", "") if isinstance(e, dict) else ""
        cat, _, slug = key.partition("/")
        if not (cat and slug and e.get("name")):
            problems.append(f"malformed entry: {str(e)[:80]}")
            continue
        if not (kb / "pages" / cat / f"{slug}.md").exists():
            missing_pages.append(key)
    if missing_pages:
        problems.append(f"{len(missing_pages)} entries without a page, e.g. {', '.join(missing_pages[:5])}")

    if problems:
        raise InvalidKB("; ".join(problems))
    return {"count": count, "categories": sorted(seen)}


def pack(kb: Path, out: Path, version: str | None = None) -> dict:
    """Stamp the version into meta.json, zip the KB (files at the zip root) and write the manifest."""
    version = version or time.strftime("%Y.%m.%d.%H%M", time.gmtime())
    meta_path = kb / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta["version"] = version
    meta_path.write_text(json.dumps(meta, indent=1), encoding="utf-8")

    out.mkdir(parents=True, exist_ok=True)
    zpath = out / "kb.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(p for p in kb.rglob("*") if p.is_file()):
            z.write(f, f.relative_to(kb).as_posix())
    manifest = {"version": version, "sha256": hashlib.sha256(zpath.read_bytes()).hexdigest(),
                "url": f"https://github.com/{REPO}/releases/latest/download/kb.zip"}
    (out / "kb-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("kb", type=Path)
    v.add_argument("--previous", type=Path)
    v.add_argument("--min-entities", type=int, default=1)
    p = sub.add_parser("pack")
    p.add_argument("kb", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--version")
    a = ap.parse_args(argv)

    try:
        if a.cmd == "validate":
            print("KB valid:", json.dumps(validate(a.kb, a.previous, a.min_entities)))
        else:
            print("Packed:", json.dumps(pack(a.kb, a.out, a.version)))
    except InvalidKB as e:
        print(f"::error::Knowledge base rejected: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
