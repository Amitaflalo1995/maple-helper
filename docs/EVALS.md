# Answer evals

`evals/answers.json` holds ~60 questions written the way players ask them (mostly Hebrew, with
transliterations like "בלו סנייל", "מאנו"), each with checks whose expected facts come from the real
knowledge base in `data/kb`. `tools/eval_answers.py` scores answers against them.

## Two modes

| | `--mode quick` (default) | `--mode claude` |
|---|---|---|
| What it tests | `maplehelper/quick.py` (instant answers) | the real `Brain`: prompt, KB context, Claude |
| Cases | those with `"instant"` set | all (or `--limit N`, `--only id1,id2`) |
| Cost | free, no network, a few seconds | **spends plan usage on your Claude account**, ~10-30 s per case |
| Where it runs | by hand and in pytest (`tests/test_answer_evals.py`, skipped without `data/kb`) | by hand only; refuses under CI or pytest |
| Fails when | any case fails (exit 1) | a case that passed in the previous report fails now (exit 1) |

```powershell
$env:PYTHONPATH = "C:\path\to\MapleHelper"
.venv\Scripts\python.exe tools\eval_answers.py                    # quick
.venv\Scripts\python.exe tools\eval_answers.py --mode claude       # asks before spending usage
.venv\Scripts\python.exe tools\eval_answers.py --mode claude --only where-mano-en,npc-shanks-he --yes
```

Claude mode saves `evals/reports/<timestamp>.json` (gitignored: answer texts, timings, cost) and lists
**regressions** (passed last time, fail now) and fixes against the newest earlier report.

## When to run Claude mode

- Before a release that changes `SYSTEM_PROMPT`, `REPLY_RULES`, `build_prompt`, the model, or anything else
  in `brain.py` that shapes answers. Run it once on the current release first if there is no recent report,
  so the comparison has a baseline.
- After a knowledge-base change that renames or restructures pages Claude reads.
- Not for quick.py changes: quick mode covers those for free.

Claude answers vary between runs. A single failure on a fuzzy case (training spots, guides) is worth reading
in the report before acting on it; a run of failures in one kind is a real regression.

## Adding a case

```json
{"id": "where-lupin-he", "question": "באיזו מפה יש לופין", "lang": "he", "kind": "where",
 "checks": {"must_mention": ["Monkey Swamp I"], "entities_include": ["monster/35"], "instant": true}}
```

- `id`: lowercase-with-dashes, unique. `lang`: `he` or `en`. `kind`: stats, drops, who_drops, where, npc,
  quest, job, training, guide, judgement, screenshot.
- Take every expected fact from `data/kb` (`index.json` props, the page under `pages/`), never from memory or
  from what the app currently answers. Prefer distinctive values (HP 7420, not Level 2).
- Checks (matching ignores case and thousands separators: "7,420" = "7420"; the answer text plus the names
  on its cards are searched):
  - `must_mention`: every string must appear.
  - `must_mention_any`: at least one must appear (for open questions such as training spots).
  - `must_not_mention`: none may appear.
  - `entities_include`: KB keys that must be among the answer's cards (entities or drop groups).
  - `instant`: `true` = quick.py must answer it, correctly; `false` = quick.py must leave it to Claude
    (judgement, "should I", the screenshot, two questions in one). Leave it out when the case is for
    Claude mode only (NPCs, quests, guides).
- Run quick mode. If a new case fails because quick.py is wrong, fix quick.py with a regression test in
  `tests/test_quick.py`; don't weaken the case to match the bug.
