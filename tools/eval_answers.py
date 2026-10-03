"""Answer-quality evals: real player questions (evals/answers.json) scored against the real knowledge base.

    python tools/eval_answers.py                                   # quick mode: instant answers only, free, seconds
    python tools/eval_answers.py --mode claude [--limit N] [--only id1,id2] [--yes]

Quick mode checks maplehelper/quick.py: every case with "instant" set must be answered instantly and correctly
(instant: true) or left to Claude (instant: false). It needs no network and fails (exit 1) on any miss, so it
runs in pytest too.

Claude mode sends each question through the real Brain, i.e. Claude Code on YOUR Claude account: every case
spends plan usage. It is for the run before a release that touches prompts or brain.py, never for CI. Results go
to evals/reports/<timestamp>.json (gitignored) and are compared with the previous report, so a prompt change that
breaks answers that used to pass shows up as a regression (exit 1).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CASES = ROOT / "evals" / "answers.json"
REPORTS = ROOT / "evals" / "reports"
KB = ROOT / "data" / "kb"            # the repo's KB, not a downloaded update: results must be reproducible

LANGS = {"he", "en"}
KINDS = {"stats", "drops", "who_drops", "where", "npc", "quest", "job", "training", "guide", "judgement", "screenshot"}
CHECKS = {"must_mention", "must_mention_any", "must_not_mention", "entities_include", "instant"}


# ------------------------------------------------------------------ cases

def load_cases(path: Path = CASES) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def validate_cases(cases: list[dict]) -> list[str]:
    """Every problem in the case file, so a typo fails loudly instead of silently skipping a check."""
    problems, seen = [], set()
    for i, c in enumerate(cases):
        cid = c.get("id") or f"#{i}"
        if not c.get("id") or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", c["id"]):
            problems.append(f"{cid}: id must be lowercase-with-dashes")
        if cid in seen:
            problems.append(f"{cid}: duplicate id")
        seen.add(cid)
        extra = set(c) - {"id", "question", "lang", "kind", "checks", "note"}
        if extra:
            problems.append(f"{cid}: unknown fields {sorted(extra)}")
        if not isinstance(c.get("question"), str) or not c["question"].strip():
            problems.append(f"{cid}: empty question")
        if c.get("lang") not in LANGS:
            problems.append(f"{cid}: lang must be one of {sorted(LANGS)}")
        if c.get("kind") not in KINDS:
            problems.append(f"{cid}: kind must be one of {sorted(KINDS)}")
        checks = c.get("checks")
        if not isinstance(checks, dict) or not checks:
            problems.append(f"{cid}: checks must be a non-empty object")
            continue
        if set(checks) - CHECKS:
            problems.append(f"{cid}: unknown checks {sorted(set(checks) - CHECKS)}")
        for name in CHECKS - {"instant"}:
            v = checks.get(name)
            if v is not None and not (isinstance(v, list) and v and all(isinstance(s, str) and s for s in v)):
                problems.append(f"{cid}: {name} must be a non-empty list of strings")
        if "instant" in checks and not isinstance(checks["instant"], bool):
            problems.append(f"{cid}: instant must be true or false")
        if checks.get("instant") is True and not (checks.get("must_mention") or checks.get("must_mention_any")):
            problems.append(f"{cid}: an instant case needs something to check in the answer")
    return problems


# ------------------------------------------------------------------ scoring

def _norm(s: str) -> str:
    """Case, curly apostrophes, thousands separators and no-break spaces don't matter: "7,420" is "7420", and a
    Hebrew answer's "Crimson Balrog" (kept on one line with a no-break space) is "Crimson Balrog"."""
    s = s.lower().replace("’", "'").replace("\u00a0", " ")
    return re.sub(r"(?<=\d),(?=\d{3})", "", s)


def answer_keys(answer) -> list[str]:
    """The keys an answer shows as cards: its entities plus the "who drops it" groups."""
    keys = list(answer.entities or [])
    for g in answer.drop_groups or []:
        keys += [g.get("monster", "")] + list(g.get("items") or [])
    return [k for k in keys if k]


def haystack(answer, kb) -> str:
    """What the player sees: the text and the names on the cards (an instant drops answer lists items as cards)."""
    names = [(kb.get(k) or {}).get("name", "") for k in answer_keys(answer)]
    return _norm("\n".join([answer.text or ""] + names))


def score(checks: dict, answer, kb) -> list[str]:
    """Problems with one answer (empty = pass). Only the content checks: "instant" is the caller's business."""
    hay = haystack(answer, kb)
    problems = [f"missing '{s}'" for s in checks.get("must_mention", []) if _norm(s) not in hay]
    anyof = checks.get("must_mention_any")
    if anyof and not any(_norm(s) in hay for s in anyof):
        problems.append("none of " + ", ".join(f"'{s}'" for s in anyof))
    problems += [f"mentions '{s}'" for s in checks.get("must_not_mention", []) if _norm(s) in hay]
    keys = set(answer_keys(answer))
    problems += [f"no card for {k}" for k in checks.get("entities_include", []) if k not in keys]
    return problems


def _result(case: dict, answer, problems: list[str], **extra) -> dict:
    return {"id": case["id"], "lang": case["lang"], "kind": case["kind"], "ok": not problems, "problems": problems,
            "text": answer.text if answer else None, "entities": answer_keys(answer) if answer else [], **extra}


# ------------------------------------------------------------------ modes

def run_quick(cases: list[dict], kb) -> list[dict]:
    """Every case with "instant" set, against quick.answer only (no network)."""
    from maplehelper import quick
    from maplehelper.i18n import I18n

    results = []
    for c in cases:
        checks = c["checks"]
        if "instant" not in checks:
            continue
        a = quick.answer(c["question"], kb, I18n(c["lang"]))
        if not checks["instant"]:
            problems = [] if a is None else ["answered instantly, should go to Claude: " + a.text.split("\n")[0]]
        elif a is None:
            problems = ["fell through to Claude, expected an instant answer"]
        else:
            problems = score(checks, a, kb)
        results.append(_result(c, a, problems))
    return results


def run_claude(cases: list[dict], kb, model: str = "sonnet", on_result=None) -> list[dict]:
    """Each case through the real Brain, one at a time. Costs plan usage: see the module docstring."""
    from maplehelper.brain import Brain

    brain = Brain(kb, model=model)
    if not brain.available():
        raise SystemExit("Claude Code was not found: install it and log in first.")
    results = []
    try:
        for c in cases:
            start = time.monotonic()
            a = brain.ask(c["question"], None, None, None)
            secs = round(time.monotonic() - start, 1)
            problems = [f"error: {a.error}"] if a.error else score(c["checks"], a, kb)
            results.append(_result(c, a, problems, seconds=secs, cost_usd=a.cost_usd))
            if on_result:
                on_result(results[-1])
    finally:
        brain.shutdown()          # ask() leaves a pre-warmed Claude Code process behind
    return results


# ------------------------------------------------------------------ reports

def save_report(results: list[dict], model: str, folder: Path = REPORTS) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (time.strftime("%Y%m%d-%H%M%S") + ".json")
    report = {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "claude", "model": model,
              "passed": sum(r["ok"] for r in results), "total": len(results), "results": results}
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def previous_report(folder: Path = REPORTS, before: Path | None = None) -> dict | None:
    """The newest report older than `before` (names are timestamps, so they sort by time)."""
    paths = sorted(p for p in folder.glob("*.json") if before is None or p.name < before.name)
    return json.loads(paths[-1].read_text(encoding="utf-8")) if paths else None


def compare(previous: dict | None, results: list[dict]) -> tuple[list[str], list[str]]:
    """(regressions, fixed): cases that passed last time and fail now, and the other way round.
    Cases missing from either run (--only, --limit, new cases) are not compared."""
    if not previous:
        return [], []
    before = {r["id"]: r["ok"] for r in previous.get("results", [])}
    regressions = [r["id"] for r in results if before.get(r["id"]) is True and not r["ok"]]
    fixed = [r["id"] for r in results if before.get(r["id"]) is False and r["ok"]]
    return regressions, fixed


# ------------------------------------------------------------------ output

def print_table(results: list[dict]) -> None:
    w = max((len(r["id"]) for r in results), default=10)
    for r in results:
        extra = f"  {r['seconds']}s" if r.get("seconds") is not None else ""
        why = "" if r["ok"] else "  " + "; ".join(r["problems"])
        print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['id']:<{w}}  {r['lang']}  {r['kind']:<10}{extra}{why}")
    passed = sum(r["ok"] for r in results)
    pct = 100 * passed / len(results) if results else 0
    print(f"\nscore: {passed}/{len(results)} ({pct:.0f}%)")


WARNING = """\
!! Claude mode runs {n} question(s) through Claude Code on YOUR Claude account.
!! Every question spends plan usage (roughly one normal question each). Model: {model}.
"""


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Hebrew on a Windows console
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="Score Maple Helper answers against evals/answers.json.")
    ap.add_argument("--mode", choices=["quick", "claude"], default="quick")
    ap.add_argument("--cases", type=Path, default=CASES)
    ap.add_argument("--kb", type=Path, default=KB)
    ap.add_argument("--limit", type=int, help="claude mode: only the first N cases")
    ap.add_argument("--only", help="comma-separated case ids")
    ap.add_argument("--model", default="sonnet", help="claude mode: model passed to Claude Code (as the app does)")
    ap.add_argument("--yes", action="store_true", help="claude mode: skip the plan-usage confirmation")
    args = ap.parse_args(argv)

    from maplehelper.kb import KnowledgeBase

    cases = load_cases(args.cases)
    problems = validate_cases(cases)
    if problems:
        print("evals file is invalid:\n  " + "\n  ".join(problems))
        return 2
    if args.only:
        wanted = [s.strip() for s in args.only.split(",") if s.strip()]
        unknown = set(wanted) - {c["id"] for c in cases}
        if unknown:
            print("unknown case ids: " + ", ".join(sorted(unknown)))
            return 2
        cases = [c for c in cases if c["id"] in wanted]
    if not (args.kb / "index.json").exists():
        print(f"no knowledge base at {args.kb}")
        return 2
    kb = KnowledgeBase(args.kb)

    if args.mode == "quick":
        results = run_quick(cases, kb)
        print_table(results)
        return 0 if all(r["ok"] for r in results) else 1

    if os.environ.get("CI") or os.environ.get("PYTEST_CURRENT_TEST"):
        print("claude mode spends a real player's plan usage: refusing to run in CI or under pytest.")
        return 2
    if args.limit:
        cases = cases[:args.limit]
    print(WARNING.format(n=len(cases), model=args.model))
    if not args.yes:
        if not sys.stdin.isatty():
            print("not a terminal: pass --yes to confirm.")
            return 2
        try:
            if input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
                return 2
        except EOFError:          # some shells report a tty with nothing behind it
            print("\nno answer: pass --yes to confirm.")
            return 2
    results = run_claude(cases, kb, args.model,
                         on_result=lambda r: print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['id']}  ({r['seconds']}s)", flush=True))
    print()
    print_table(results)
    path = save_report(results, args.model)
    regressions, fixed = compare(previous_report(before=path), results)
    print(f"report: {path.relative_to(ROOT)}")
    if fixed:
        print("fixed since the previous report: " + ", ".join(fixed))
    if regressions:
        print("REGRESSIONS (passed in the previous report, fail now): " + ", ".join(regressions))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
