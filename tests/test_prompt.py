"""The system prompt is a str.format template: literal JSON braces must be doubled."""
from maplehelper.brain import LENGTH, SYSTEM_PROMPT


def test_system_prompt_formats():
    for length in LENGTH.values():
        text = SYSTEM_PROMPT.format(length=length)
        assert "drop_groups" in text and "{length}" not in text
