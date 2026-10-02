"""The MapleStory Classic job tree, and turning what the AI read off the HUD into a consistent class + job."""
from __future__ import annotations

# base class -> [(job, min level)]
JOBS = {
    "Beginner": [("Beginner", 1)],
    "Warrior": [("Beginner", 1), ("Warrior", 10), ("Fighter", 30), ("Page", 30), ("Spearman", 30),
                ("Crusader", 70), ("White Knight", 70), ("Dragon Knight", 70)],
    "Magician": [("Beginner", 1), ("Magician", 8), ("F/P Wizard", 30), ("I/L Wizard", 30), ("Cleric", 30),
                 ("F/P Mage", 70), ("I/L Mage", 70), ("Priest", 70)],
    "Bowman": [("Beginner", 1), ("Bowman", 10), ("Hunter", 30), ("Crossbowman", 30), ("Ranger", 70), ("Sniper", 70)],
    "Thief": [("Beginner", 1), ("Thief", 10), ("Assassin", 30), ("Bandit", 30), ("Hermit", 70), ("Chief Bandit", 70)],
}
# other names for the same job: older clients and servers print these on the HUD (an Old School HUD says "Archer")
ALIASES = {"archer": "Bowman", "swordman": "Warrior", "swordsman": "Warrior", "rogue": "Thief", "mage": "Magician",
           "wizard": "Magician", "crossbow man": "Crossbowman", "fire/poison wizard": "F/P Wizard",
           "ice/lightning wizard": "I/L Wizard", "fire/poison mage": "F/P Mage", "ice/lightning mage": "I/L Mage"}


def canonical_job(name: str) -> str | None:
    """'Archer' -> 'Bowman', 'assassin' -> 'Assassin'; None when it's no job of the tree."""
    n = " ".join(str(name).split()).lower()
    n = ALIASES.get(n, n).lower()
    for jobs in JOBS.values():
        for job, _ in jobs:
            if job.lower() == n:
                return job
    return None


def class_of(job: str) -> str | None:
    """The base class a job belongs to (Beginner belongs to every class: None)."""
    if job == "Beginner":
        return None
    return next((c for c, jobs in JOBS.items() if any(j == job for j, _ in jobs)), None)


def canonical_class(name: str) -> str | None:
    n = " ".join(str(name).split()).lower()
    n = ALIASES.get(n, n).lower()
    return next((c for c in JOBS if c.lower() == n), None) or class_of(canonical_job(name) or "")


def first_job(base_class: str, level: int) -> str:
    """The job a character of this class has at least: its 1st job once the level allows it, else Beginner."""
    jobs = JOBS.get(base_class, [])
    return jobs[1][0] if len(jobs) > 1 and level >= jobs[1][1] else "Beginner"
