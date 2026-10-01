"""Settings, character profiles and conversation history."""
import json


def test_settings_defaults_and_persistence(isolated_store):
    s = isolated_store.Settings()
    assert s["hotkey_toggle"] == "F9" and s["language"] is None
    s["language"] = "en"
    assert json.loads(isolated_store.Settings.path.read_text(encoding="utf-8"))["language"] == "en"
    assert isolated_store.Settings()["language"] == "en"


def test_settings_keep_new_defaults_for_old_files(isolated_store):
    isolated_store.Settings.path.write_text('{"language": "he"}', encoding="utf-8")
    s = isolated_store.Settings()
    assert s["language"] == "he" and s["appearance"] == "light"


def test_provider_defaults_to_claude(isolated_store):
    assert isolated_store.Settings()["provider"] == "claude"


class TestApiKeyMode:
    def test_legacy_flag_belongs_to_claude(self, isolated_store):
        # settings written before Codex support kept a single bool for the Anthropic key
        isolated_store.Settings.path.write_text('{"api_key_fallback": true}', encoding="utf-8")
        s = isolated_store.Settings()
        assert s.api_key_mode("claude") and not s.api_key_mode("codex")

    def test_each_provider_keeps_its_own_flag(self, isolated_store):
        s = isolated_store.Settings()
        s.set_api_key_mode("codex", True)
        assert s.api_key_mode("codex") and not s.api_key_mode("claude")
        s.set_api_key_mode("claude", True)
        s.set_api_key_mode("codex", False)
        again = isolated_store.Settings()
        assert again.api_key_mode("claude") and not again.api_key_mode("codex")


def test_corrupt_settings_fall_back_to_defaults(isolated_store):
    isolated_store.Settings.path.write_text("{oops", encoding="utf-8")
    assert isolated_store.Settings()["font_size"] == 14


class TestProfiles:
    def make(self, store):
        p = store.Profiles()
        p.add("Tal", "Warrior", "Warrior", 12)
        return p

    def test_add_sets_active_and_persists(self, isolated_store):
        self.make(isolated_store)
        again = isolated_store.Profiles()
        assert again.active.name == "Tal" and again.active.level == 12

    def test_apply_update(self, isolated_store):
        p = self.make(isolated_store)
        changed = p.apply_update({"level": "30", "job": "Fighter", "map": "Perion",
                                  "quests_started": ["Q1", "Q2"], "note": "wants Power Strike"})
        assert ("level", 30) in changed and ("job", "Fighter") in changed
        assert p.active.active_quests == ["Q1", "Q2"]
        changed = p.apply_update({"quests_completed": ["Q1", "missing"], "note": "wants Power Strike"})
        assert changed == [("quest-", "Q1")]        # duplicate note and unknown quest are ignored
        assert isolated_store.Profiles().active.active_quests == ["Q2"]

    def test_apply_update_rejects_bad_levels(self, isolated_store):
        p = self.make(isolated_store)
        for bad in (0, 251, "abc", None, ""):
            assert p.apply_update({"level": bad}) == []
        assert p.active.level == 12

    def test_no_active_character(self, isolated_store):
        assert isolated_store.Profiles().apply_update({"level": 5}) == []

    def test_summary(self, isolated_store):
        c = self.make(isolated_store).active
        c.notes = [f"n{i}" for i in range(15)]
        s = c.summary()
        assert "Level: 12" in s and "n14" in s and "n4" not in s   # only the last 10 notes


class TestHistory:
    def test_recent_and_corrupt_lines(self, isolated_store):
        h = isolated_store.History("abc")
        for i in range(25):
            h.append("user", f"msg {i}")
        with h.log.open("a", encoding="utf-8") as f:
            f.write("not json\n")
        recent = h.recent()
        assert len(recent) == 19 and recent[-1]["text"] == "msg 24"

    def test_summaries_roll_and_clear(self, isolated_store):
        h = isolated_store.History("abc")
        for i in range(12):
            h.add_summary(f"s{i}")
        assert h.summaries() == [f"s{i}" for i in range(2, 12)]
        h.clear()
        assert h.recent() == [] and h.summaries() == []
