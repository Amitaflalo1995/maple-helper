"""macOS layer logic that needs no Mac: window matching, hotkey codes, the login item (pyobjc/Carbon load lazily)."""
import ctypes
import plistlib

from maplehelper import macapi

OWN_PID = 4242


def win(number, name="", owner="", pid=100, layer=0, w=1280, h=720):
    return {"kCGWindowNumber": number, "kCGWindowName": name, "kCGWindowOwnerName": owner,
            "kCGWindowOwnerPID": pid, "kCGWindowLayer": layer,
            "kCGWindowBounds": {"X": 0, "Y": 25, "Width": w, "Height": h}}


def test_picks_the_game_by_title():
    infos = [win(1, "Safari", "Safari"), win(7, "MapleStory Classic", "wine64-preloader")]
    assert macapi.pick_game_window(infos, OWN_PID) == 7


def test_picks_the_game_by_owner_without_screen_recording():
    # no Screen Recording grant: macOS hides window titles, the owning app's name still shows
    assert macapi.pick_game_window([win(3, "", "MapleStory")], OWN_PID) == 3


def test_frontmost_match_wins():
    infos = [win(5, "MapleStory Classic"), win(6, "MapleStory Classic")]
    assert macapi.pick_game_window(infos, OWN_PID) == 5


def test_skips_own_windows_menu_bar_and_tiny_windows():
    infos = [
        win(1, "Maple Helper", "Maple Helper", pid=OWN_PID),        # the overlay itself
        win(2, "MapleStory updates", "Python", pid=OWN_PID),         # anything of ours
        win(3, "MapleStory", "Menu bar", layer=25),                  # status item, not a document window
        win(4, "MapleStory", "Launcher", w=40, h=40),                # tiny helper window
        win(5, "Maple Helper - notes", "TextEdit"),                  # someone else's window about us
    ]
    assert macapi.pick_game_window(infos, OWN_PID) is None


def test_no_game_running():
    assert macapi.pick_game_window([win(1, "Finder", "Finder")], OWN_PID) is None


def test_every_hotkey_choice_has_a_mac_key_code():
    assert set(macapi.KEYCODES) == {f"F{i}" for i in range(1, 13)}
    assert len(set(macapi.KEYCODES.values())) == 12


def test_carbon_constants_and_struct_layout():
    # Carbon reads these by value/pointer: the layouts must match HIToolbox exactly
    assert macapi.fourcc("keyb") == 0x6B657962
    assert macapi.kEventParamDirectObject == 0x2D2D2D2D
    assert ctypes.sizeof(macapi.EventHotKeyID) == 8
    assert ctypes.sizeof(macapi.EventTypeSpec) == 8


def test_autostart_writes_and_removes_a_launch_agent(tmp_path, monkeypatch):
    agent = tmp_path / "LaunchAgents" / "com.maplehelper.app.plist"
    exe = "/Applications/Maple Helper.app/Contents/MacOS/Maple Helper"
    monkeypatch.setattr(macapi.sys, "frozen", True, raising=False)
    monkeypatch.setattr(macapi.sys, "executable", exe)

    macapi.set_autostart(True, ["--background"], agent)
    data = plistlib.loads(agent.read_bytes())
    assert data["Label"] == "com.maplehelper.app"
    assert data["ProgramArguments"] == [exe, "--background"]
    assert data["RunAtLoad"] is True

    macapi.set_autostart(False, ["--background"], agent)
    assert not agent.exists()
    macapi.set_autostart(False, ["--background"], agent)   # already off: no error


def test_autostart_from_source_runs_the_module(tmp_path, monkeypatch):
    agent = tmp_path / "agent.plist"
    monkeypatch.delattr(macapi.sys, "frozen", raising=False)
    monkeypatch.setattr(macapi.sys, "executable", "/usr/local/bin/python3")
    macapi.set_autostart(True, ["--background"], agent)
    assert plistlib.loads(agent.read_bytes())["ProgramArguments"] == ["/usr/local/bin/python3", "-m", "maplehelper",
                                                                       "--background"]
