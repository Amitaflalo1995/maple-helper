"""Every UI string exists in Hebrew and English with the same placeholders."""
import string

import pytest

from maplehelper.i18n import STRINGS, I18n


def fields(s: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(s) if f}


@pytest.mark.parametrize("key", sorted(STRINGS))
def test_both_languages_with_same_placeholders(key):
    entry = STRINGS[key]
    assert entry.get("he") and entry.get("en"), f"{key} is missing a language"
    assert fields(entry["he"]) == fields(entry["en"]), f"{key} placeholders differ"


def test_lookup_and_fallbacks():
    assert I18n("en")("hotkey_taken", key="F9").startswith("F9 is taken")
    assert I18n("xx").lang == "he" and I18n("he").rtl and not I18n("en").rtl
    assert I18n("en")("no_such_key") == "no_such_key"
