"""The wishlist: per character, toggled from item cards, flagged when a KB update touches it."""
from types import SimpleNamespace

from maplehelper import wishlist


class FakeSettings(dict):
    def __getitem__(self, k):
        return self.get(k)


def test_toggle_is_per_character():
    s = FakeSettings(wishlist={})
    assert wishlist.toggle(s, "kiwi", "item/1") is True
    assert wishlist.items(s, "kiwi") == ["item/1"] and wishlist.items(s, "other") == []
    assert wishlist.toggle(s, "kiwi", "item/1") is False
    assert wishlist.items(s, "kiwi") == []


def test_kb_update_touching_a_wished_item_is_flagged():
    kb = SimpleNamespace(get=lambda k: {"item/1": {"name": "Blue Potion"}, "item/2": {"name": "Ilbi"}}.get(k))
    entries = [{"changed": [{"key": "monster/2", "name": "Snail", "drops_added": ["Blue Potion"]}],
                "added": [{"key": "item/2", "name": "Ilbi"}]}]
    assert set(wishlist.touched(entries, ["item/1", "item/2"], kb)) == {"Blue Potion", "Ilbi"}
    assert wishlist.touched(entries, [], kb) == []
