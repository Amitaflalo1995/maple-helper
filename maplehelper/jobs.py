"""The MapleStory Classic job tree, and turning what the AI read off the HUD into a consistent class + job."""
from __future__ import annotations

import re

# base class -> [(job, min level)], from the KB: the 1st job at level 10 for every class, Magician too
# (pages/guide/maplestory-classic-glossary.md: "The first real job you pick at level 10: Warrior, Magician, Bowman,
# Thief"), the 2nd job at 30 (pages/class/<class>.md: "... branch into ... at level 30"), the 3rd at 70
# (pages/class/bowman.md: "Bowmen advance again at level 70"). tests/test_jobs.py checks this against the KB.
JOBS = {
    "Beginner": [("Beginner", 1)],
    "Warrior": [("Beginner", 1), ("Warrior", 10), ("Fighter", 30), ("Page", 30), ("Spearman", 30),
                ("Crusader", 70), ("White Knight", 70), ("Dragon Knight", 70)],
    "Magician": [("Beginner", 1), ("Magician", 10), ("F/P Wizard", 30), ("I/L Wizard", 30), ("Cleric", 30),
                 ("F/P Mage", 70), ("I/L Mage", 70), ("Priest", 70)],
    "Bowman": [("Beginner", 1), ("Bowman", 10), ("Hunter", 30), ("Crossbowman", 30), ("Ranger", 70), ("Sniper", 70)],
    "Thief": [("Beginner", 1), ("Thief", 10), ("Assassin", 30), ("Bandit", 30), ("Hermit", 70), ("Chief Bandit", 70)],
}
# 3rd job isn't in the launch build (pages/guide/attacks-you-can-use-mid-jump.md: "Third job isn't available at
# launch"; pages/guide/assassin-class-guide.md: "Third job and El Nath are not in the launch build"): the plan's
# "next job" stops at the 2nd. Set to 3 once it opens.
MAX_JOB_TIER = 2
# other names for the same job: older clients and servers print these on the HUD (an Old School HUD says "Archer"),
# and players type them ("FP Wizard", "Bowmen"); keys are compared lowercase without punctuation (_key)
ALIASES = {"archer": "Bowman", "bowmen": "Bowman", "swordman": "Warrior", "swordsman": "Warrior", "rogue": "Thief",
           "mage": "Magician", "wizard": "Magician", "crossbow man": "Crossbowman", "crossbowmen": "Crossbowman",
           "spear man": "Spearman", "fire poison wizard": "F/P Wizard", "wizard fire poison": "F/P Wizard",
           "fp wizard": "F/P Wizard", "ice lightning wizard": "I/L Wizard", "wizard ice lightning": "I/L Wizard",
           "il wizard": "I/L Wizard", "fire poison mage": "F/P Mage", "fp mage": "F/P Mage",
           "ice lightning mage": "I/L Mage", "il mage": "I/L Mage"}


def _key(name: str) -> str:
    """'Wizard (Fire,Poison)' -> 'wizard fire poison', 'F/P Wizard' -> 'fp wizard': no punctuation or brackets."""
    n = str(name).lower().replace("/", "")
    return " ".join(re.sub(r"[^\w\s]", " ", n).split())


_JOB_KEYS = {_key(job): job for jobs in JOBS.values() for job, _ in jobs}
_ALIAS_KEYS = {_key(a): v for a, v in ALIASES.items()}


def canonical_job(name: str) -> str | None:
    """'Archer' -> 'Bowman', 'assassin' -> 'Assassin', 'Wizard (Fire,Poison)' -> 'F/P Wizard';
    None when it's no job of the tree."""
    n = _key(name)
    n = _key(_ALIAS_KEYS.get(n, n))
    return _JOB_KEYS.get(n)


def class_of(job: str) -> str | None:
    """The base class a job belongs to (Beginner belongs to every class: None)."""
    if job == "Beginner":
        return None
    return next((c for c, jobs in JOBS.items() if any(j == job for j, _ in jobs)), None)


def canonical_class(name: str) -> str | None:
    n = _key(name)
    n = _key(_ALIAS_KEYS.get(n, n))
    return next((c for c in JOBS if c.lower() == n), None) or class_of(canonical_job(name) or "")


def first_job(base_class: str, level: int) -> str:
    """The job a character of this class has at least: its 1st job once the level allows it, else Beginner."""
    jobs = JOBS.get(base_class, [])
    return jobs[1][0] if len(jobs) > 1 and level >= jobs[1][1] else "Beginner"


def tier_levels(base_class: str) -> list[int]:
    """The levels of the class's advancements, open ones only: [1, 10, 30] while 3rd job isn't out."""
    levels = sorted({lv for _, lv in JOBS.get(base_class, [])})
    return levels[:MAX_JOB_TIER + 1]
