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


def test_profiles_written_by_a_newer_version_still_load(tmp_path, monkeypatch):
    """A newer version (or a preview build) may save fields this one doesn't know: skip them, don't crash."""
    import json

    from maplehelper import store
    monkeypatch.setattr(store.Profiles, "path", tmp_path / "profiles.json")
    (tmp_path / "profiles.json").write_text(json.dumps({"active": "a", "characters": [
        {"id": "a", "name": "Kiwi", "base_class": "Thief", "job": "Assassin", "level": 34, "from_the_future": 1}]}))
    p = store.Profiles()
    assert p.active.name == "Kiwi" and p.active.level == 34


def test_launch_waits_for_a_running_update(monkeypatch):
    from maplehelper import setupwait
    states = iter([True, True, False])
    monkeypatch.setattr(setupwait, "setup_running", lambda: next(states))
    assert setupwait.wait_for_setup(limit_s=5, step_s=0) is True
    monkeypatch.setattr(setupwait, "setup_running", lambda: False)
    assert setupwait.wait_for_setup(limit_s=5, step_s=0) is False


def test_damaged_install_is_explained_not_a_traceback(tmp_path, monkeypatch):
    """A missing file of the install (e.g. shiboken6.Shiboken) shows a reinstall prompt and logs the error."""
    import ctypes
    import sys
    import webbrowser

    from maplehelper import setupwait, store
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    shown, opened = [], []
    if sys.platform == "win32":
        monkeypatch.setattr(ctypes.windll.user32, "MessageBoxW", lambda *a: shown.append(a) or 6)
    monkeypatch.setattr(webbrowser, "open", opened.append)
    setupwait.report_broken_install(ModuleNotFoundError("No module named 'shiboken6.Shiboken'"))
    assert "shiboken6.Shiboken" in (tmp_path / "logs" / "startup-error.log").read_text(encoding="utf-8")
    if sys.platform == "win32":
        assert shown and opened == [setupwait.DOWNLOAD_URL]


def test_malformed_ai_profile_update_is_ignored(isolated_store):
    """A reply with {"name": ...} or lists where text belongs once broke every later start."""
    p = isolated_store.Profiles()
    p.add("Amit", "Warrior", "Fighter", 30)
    changed = p.apply_update({"map": {"name": "Henesys"}, "job": ["Page"], "note": ["x"],
                              "quests_started": "Pio's Quest", "quests_completed": [{"name": "y"}]})
    assert changed == [("quest+", "Pio's Quest")]
    assert p.apply_update(["not", "a", "dict"]) == []
    c = isolated_store.Profiles().active
    assert c.map == "" and c.job == "Fighter" and c.active_quests == ["Pio's Quest"] and c.notes == []
    assert "Pio's Quest" in c.summary()


def test_profiles_drop_bad_saved_values_on_load(isolated_store):
    isolated_store.Profiles.path.write_text(json.dumps({"active": "a", "characters": [
        {"id": "a", "name": "Amit", "base_class": "Warrior", "job": "Fighter", "level": 30,
         "map": {"name": "Henesys"}, "notes": [["x"]]},
        "garbage", {"id": "b"}]}), encoding="utf-8")
    p = isolated_store.Profiles()
    assert [c.id for c in p.characters] == ["a"]
    assert p.active.map == "" and p.active.notes == []


def test_hud_job_names_keep_class_and_job_consistent(isolated_store):
    """An Old School HUD says "Archer": the class becomes Bowman and an old Thief job doesn't survive."""
    p = isolated_store.Profiles()
    p.add("Kalimero", "Thief", "Assassin", 30)
    p.apply_update({"level": 15, "job": "Archer", "base_class": "Archer"})
    c = p.active
    assert (c.base_class, c.job, c.level) == ("Bowman", "Bowman", 15)
    assert c.job_label == "Archer"           # the card says what the game says
    p.apply_update({"job": "Hunter"})
    assert (p.active.base_class, p.active.job) == ("Bowman", "Hunter") and p.active.job_label == "Hunter"
    p.apply_update({"base_class": "Warrior", "level": 5})
    assert (p.active.base_class, p.active.job) == ("Warrior", "Beginner")
    p.apply_update({"job": "Not a job"})
    assert p.active.job == "Beginner"


def test_sync_takes_the_hud_name(isolated_store):
    p = isolated_store.Profiles()
    p.add("Kalimero", "Bowman", "Bowman", 15)
    assert p.apply_update({"name": "KalimeroZz"}) == [("name", "KalimeroZz")]
    assert p.apply_update({"name": "not a name!"}) == [] and p.active.name == "KalimeroZz"


def test_another_character_on_the_hud_is_not_the_active_one():
    from maplehelper.store import hud_name, same_character
    assert same_character("Kalimero", "KalimeroZz") and same_character("kalimerozz", "KalimeroZz")
    assert not same_character("KalimeroZz", "NewGuy99") and not same_character("Al", "Alpha")
    assert hud_name({"name": " NewGuy99 "}) == "NewGuy99" and hud_name({"name": "a b"}) is None


def test_another_name_never_renames_the_active_character(isolated_store):
    p = isolated_store.Profiles()
    p.add("KalimeroZz", "Bowman", "Bowman", 15)
    assert p.apply_update({"name": "NewGuy99"}) == [] and p.active.name == "KalimeroZz"
    assert p.find_by_name("kalimerozz") is p.active


def test_alt_with_a_longer_name_is_never_merged(isolated_store):
    """'Amit' and the alt 'AmitBow' are two characters once the HUD confirmed 'Amit', or when both are saved."""
    from maplehelper.store import same_character
    p = isolated_store.Profiles()
    p.add("Amit", "Bowman", "Bowman", 45)
    p.apply_update({"name": "Amit"})                      # the HUD confirms the name
    assert p.apply_update({"name": "AmitBow", "level": 31}) == [("level", 31)] or p.active.name == "Amit"
    assert p.active.name == "Amit"
    assert not same_character("Amit", "AmitBow", seen=False, others=("AmitBow",))
    assert same_character("Kalimero", "KalimeroZz") and not same_character("KalimeroZz", "Kalimero")
