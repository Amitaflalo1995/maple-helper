"""Answer parsing, level detection and prompt assembly (no AI calls). Providers: test_providers.py."""
import pytest

from maplehelper import brain
from maplehelper.store import Character


class TestSplitMeta:
    def test_answer_without_meta(self):
        assert brain.split_meta("  Go to Henesys.  ") == ("Go to Henesys.", {})

    def test_answer_with_meta(self):
        raw = 'Hunt **Red Snail**.\n@@META@@\n{"entities": ["monster/130101"], "profile_update": {"level": 5}}'
        text, meta = brain.split_meta(raw)
        assert text == "Hunt **Red Snail**."
        assert meta == {"entities": ["monster/130101"], "profile_update": {"level": 5}}

    def test_meta_wrapped_in_code_fence(self):
        text, meta = brain.split_meta('Hi\n@@META@@\n```json\n{"entities": []}\n```')
        assert text == "Hi" and meta == {"entities": []}

    def test_malformed_meta_is_dropped_but_text_kept(self):
        assert brain.split_meta("Hi\n@@META@@\n{not json}") == ("Hi", {})
        assert brain.split_meta("Hi\n@@META@@\n") == ("Hi", {})


@pytest.mark.parametrize("text,level", [
    ("עליתי ללבל 16", 16),
    ("הגעתי ל-30 היום", 30),
    ("אני לבל 45 עכשיו", 45),
    ("I'm level 16", 16),
    ("just hit lvl 70!", 70),
    ("reached Lv. 120", 120),
])
def test_stated_level(text, level):
    assert brain.stated_level(text) == level


@pytest.mark.parametrize("text", ["where do level 30s grind?", "Red Snail is level 4", "I'm level 999", "hello"])
def test_no_stated_level(text):
    assert brain.stated_level(text) is None


def test_kb_has(kb):
    assert brain.kb_has(kb, "monster/130101")
    assert not brain.kb_has(kb, "monster/0")


class TestBuildPrompt:
    def char(self, level=5):
        return Character(id="c1", name="Tal", base_class="Beginner", job="Beginner", level=level, map="Henesys")

    def test_contains_profile_context_and_question(self, kb):
        p = brain.build_prompt("where does Red Snail live?", self.char(), None, kb, has_screenshot=True)
        assert "<player_profile>" in p and "Level: 5" in p
        assert "[monster/130101]" in p                      # page pre-fetched for the named monster
        assert "Monsters near the player's level" in p      # level digest
        assert "<screenshot>attached above</screenshot>" in p
        assert p.rstrip().endswith("</reply_rules>")
        assert "At most 6 short lines" in p

    def test_unknown_player_and_no_screenshot(self, kb):
        p = brain.build_prompt("hello", None, None, kb, has_screenshot=False, length="detailed")
        assert "<player_profile>unknown</player_profile>" in p
        assert "not available" in p and "At most 15 short lines" in p
        assert "<kb_context>" not in p

    def test_includes_history(self, kb, isolated_store):
        h = isolated_store.History("c1")
        h.append("user", "hi there")
        h.append("assistant", "hello!")
        h.add_summary("Worked on first job advancement.")
        p = brain.build_prompt("next?", self.char(), h, kb, has_screenshot=False)
        assert "Player: hi there" in p and "Helper: hello!" in p
        assert "first job advancement" in p

    def test_system_prompt_formats(self):
        # the system prompt uses {{ }} escapes around the META JSON; a bad escape would raise here
        s = brain.SYSTEM_PROMPT.format(length=brain.LENGTH["short"])
        assert '{"entities"' in s and brain.META in s


@pytest.mark.parametrize("meta", ['{"entities": null}', '{"profile_update": []}', '{"drop_groups": 5}', '[1, 2]'])
def test_malformed_meta_keeps_the_answer(meta):
    text, data = brain.split_meta("Go to Henesys.\n@@META@@\n" + meta)
    assert text == "Go to Henesys."
    assert all(not (k in data and not isinstance(data[k], t))
               for k, t in (("entities", list), ("profile_update", dict), ("drop_groups", list)))
