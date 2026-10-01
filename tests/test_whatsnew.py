"""App release notes: every release ships its own, and players see only what's new to them."""
from maplehelper import __version__, whatsnew


def test_every_release_has_notes_in_both_languages():
    notes = {n["version"]: n for n in whatsnew.load()}
    assert __version__ in notes, f"add {__version__} to assets/notes/whatsnew.json before releasing"
    for n in notes.values():
        assert n.get("he") and n.get("en") and len(n["he"]) == len(n["en"]), n["version"]


def test_since_shows_only_unseen_versions_up_to_the_running_one(monkeypatch):
    notes = [{"version": v, "he": ["x"], "en": ["x"]} for v in ("0.5.0", "0.4.0", "0.3.0", "0.2.0")]
    monkeypatch.setattr(whatsnew, "load", lambda: notes)
    assert [n["version"] for n in whatsnew.since("0.2.0", "0.4.0")] == ["0.4.0", "0.3.0"]
    assert whatsnew.since("0.4.0", "0.4.0") == []


def test_versions_compare_as_numbers_not_text():
    assert whatsnew.version_tuple("0.10.0") > whatsnew.version_tuple("0.9.0")
