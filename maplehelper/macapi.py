"""macOS helpers, same interface as winapi.py: find the game window, capture it, focus, hotkeys, autostart.

Just as non-invasive as on Windows: no event taps, no key-state polling, no process access. Windows come
from the Quartz window list, capture is a screen grab, and keys are ordinary system hotkeys
(Carbon RegisterEventHotKey, the macOS counterpart of RegisterHotKey). The one privacy grant the player
gives is Screen Recording (window titles + the screenshot).

pyobjc and Carbon are loaded lazily, so the pure parts of this module import (and are tested) on any OS.
"""
from __future__ import annotations

import ctypes
import os
import plistlib
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .capture import grab_image, grab_jpeg

GAME_TITLES = ("MapleStory Classic", "MapleStory", "Classic World")
# virtual key codes (HIToolbox kVK_F1...). Macs send F-keys only with fn held, unless
# "Use F1, F2, etc. keys as standard function keys" is on (System Settings > Keyboard).
KEYCODES = {"F1": 122, "F2": 120, "F3": 99, "F4": 118, "F5": 96, "F6": 97,
            "F7": 98, "F8": 100, "F9": 101, "F10": 109, "F11": 103, "F12": 111}
LAUNCH_AGENT_LABEL = "com.maplehelper.app"
LAUNCH_AGENT = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
# mss on macOS takes points (Qt's logical coordinates), not physical pixels
SCREEN_COORDS_ARE_PHYSICAL = False

# NSWindowCollectionBehavior: show on every Space, including another app's fullscreen Space
_CAN_JOIN_ALL_SPACES = 1 << 0
_FULLSCREEN_AUXILIARY = 1 << 8
_ACTIVATE_IGNORING_OTHER_APPS = 1 << 1


def prepare_process() -> None:
    """Nothing to do: the bundle's Info.plist (LSUIElement) keeps the app out of the Dock."""


def missing_permissions(request: bool = False) -> list[str]:
    """['screen'] while Screen Recording is not granted. request=True shows macOS's prompt (first time only;
    after that the player flips the switch in System Settings > Privacy & Security)."""
    try:
        import Quartz
    except ImportError:
        return []
    if Quartz.CGPreflightScreenCaptureAccess():
        return []
    if request:
        Quartz.CGRequestScreenCaptureAccess()
    return ["screen"]


# ---------------------------------------------------------------- windows

def pick_game_window(infos, own_pid: int) -> int | None:
    """The game's window number from a Quartz window list (frontmost first), or None.

    Matches the window title, or the owning app's name (titles are empty without the Screen
    Recording grant). Under CrossOver/Wine the owner is a wine process, so the title is what
    identifies the game there.
    """
    for w in infos:
        if w.get("kCGWindowOwnerPID") == own_pid or w.get("kCGWindowLayer", 0) != 0:
            continue
        names = f"{w.get('kCGWindowName') or ''} {w.get('kCGWindowOwnerName') or ''}".lower()
        if "maple helper" in names:
            continue
        b = w.get("kCGWindowBounds") or {}
        if b.get("Width", 0) <= 50 or b.get("Height", 0) <= 50:
            continue
        if any(g.lower() in names for g in GAME_TITLES):
            return int(w["kCGWindowNumber"])
    return None


def _window_info(window_id: int) -> dict | None:
    import Quartz
    infos = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionIncludingWindow, window_id) or []
    return dict(infos[0]) if infos else None


def find_game_window() -> int | None:
    import Quartz
    opts = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    infos = Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) or []
    return pick_game_window([dict(w) for w in infos], os.getpid())


def window_rect(window_id) -> tuple[int, int, int, int] | None:
    """Bounds in desktop points (top-left origin, the coordinates Qt uses)."""
    info = _window_info(window_id) if window_id else None
    b = (info or {}).get("kCGWindowBounds")
    if not b:
        return None
    x, y, w, h = (int(b[k]) for k in ("X", "Y", "Width", "Height"))
    return (x, y, w, h) if w > 50 and h > 50 else None


def capture_game(window_id: int | None = None) -> bytes | None:
    """JPEG of the game window (longest side 1280px), or None if the game isn't found."""
    window_id = window_id or find_game_window()
    if not window_id:
        return None
    rect = window_rect(window_id)
    return grab_jpeg(rect) if rect else None


def grab_screen(x: int, y: int, w: int, h: int):
    """Raw RGB capture of a screen rectangle (points) → PIL image."""
    return grab_image(x, y, w, h)


def focus_window(window_id: int) -> None:
    """Bring the app owning this window to the front (macOS activates apps, not windows)."""
    info = _window_info(window_id) if window_id else None
    if not info:
        return
    from AppKit import NSRunningApplication
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(info["kCGWindowOwnerPID"])
    if app:
        app.activateWithOptions_(_ACTIVATE_IGNORING_OTHER_APPS)


def activate_self(win_id: int) -> None:
    """Bring our own app (and with it, its Qt windows) to the front."""
    from AppKit import NSApplication
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)


def float_over_fullscreen(win_id: int) -> None:
    """Let a Qt window (winId = its NSView) appear on every Space, also over a fullscreen game."""
    try:
        import objc
        window = objc.objc_object(c_void_p=ctypes.c_void_p(int(win_id))).window()
        if window is not None:
            window.setCollectionBehavior_(window.collectionBehavior() | _CAN_JOIN_ALL_SPACES | _FULLSCREEN_AUXILIARY)
    except Exception:
        pass   # cosmetic: the window still works on the game's Space when the game is windowed


# ---------------------------------------------------------------- hotkeys (Carbon)

def fourcc(code: str) -> int:
    return int.from_bytes(code.encode("ascii"), "big")


class EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


_EventHandler = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
SIGNATURE = fourcc("MplH")
kEventClassKeyboard = fourcc("keyb")
kEventHotKeyPressed = 5
kEventParamDirectObject = fourcc("----")
typeEventHotKeyID = fourcc("hkid")
eventNotHandledErr = -9874
_carbon_lib = None


def carbon():
    """Carbon's HIToolbox, with the signatures of the five calls hotkeys need."""
    global _carbon_lib
    if _carbon_lib is None:
        c = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        vp, u32, ulong = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_ulong   # ItemCount/ByteCount: unsigned long
        c.GetApplicationEventTarget.restype, c.GetApplicationEventTarget.argtypes = vp, []
        c.InstallEventHandler.restype = ctypes.c_int32
        c.InstallEventHandler.argtypes = [vp, _EventHandler, ulong, ctypes.POINTER(EventTypeSpec), vp, ctypes.POINTER(vp)]
        c.RegisterEventHotKey.restype = ctypes.c_int32
        c.RegisterEventHotKey.argtypes = [u32, u32, EventHotKeyID, vp, u32, ctypes.POINTER(vp)]
        c.UnregisterEventHotKey.restype, c.UnregisterEventHotKey.argtypes = ctypes.c_int32, [vp]
        c.GetEventParameter.restype = ctypes.c_int32
        c.GetEventParameter.argtypes = [vp, u32, u32, vp, ulong, vp, vp]
        _carbon_lib = c
    return _carbon_lib


class Hotkeys(QObject):
    """System-wide hotkeys (RegisterEventHotKey; delivered through the app's event loop). Emits pressed(hotkey_id)."""

    pressed = Signal(int)

    def __init__(self):
        super().__init__()
        c = carbon()
        self._refs: dict[int, ctypes.c_void_p] = {}
        self._handler = _EventHandler(self._on_event)   # keep a reference: Carbon holds only the pointer
        spec = EventTypeSpec(kEventClassKeyboard, kEventHotKeyPressed)
        self._handler_ref = ctypes.c_void_p()
        c.InstallEventHandler(c.GetApplicationEventTarget(), self._handler, 1, ctypes.byref(spec), None,
                              ctypes.byref(self._handler_ref))

    def _on_event(self, _call, event, _user_data) -> int:
        try:
            hk = EventHotKeyID()
            err = carbon().GetEventParameter(event, kEventParamDirectObject, typeEventHotKeyID, None,
                                             ctypes.sizeof(hk), None, ctypes.byref(hk))
            if err == 0 and hk.signature == SIGNATURE and hk.id in self._refs:
                self.pressed.emit(int(hk.id))
                return 0
        except Exception:
            pass
        return eventNotHandledErr

    def register(self, hotkey_id: int, key_name: str) -> bool:
        """(Re)binds hotkey_id to key_name. False when the key is unknown or another app owns it."""
        self.unregister(hotkey_id)
        code = KEYCODES.get(key_name)
        if code is None:
            return False
        c = carbon()
        ref = ctypes.c_void_p()
        err = c.RegisterEventHotKey(code, 0, EventHotKeyID(SIGNATURE, hotkey_id), c.GetApplicationEventTarget(), 0,
                                    ctypes.byref(ref))
        if err != 0:
            return False
        self._refs[hotkey_id] = ref
        return True

    def unregister(self, hotkey_id: int) -> None:
        ref = self._refs.pop(hotkey_id, None)
        if ref:
            carbon().UnregisterEventHotKey(ref)

    def close(self) -> None:
        for hid in list(self._refs):
            self.unregister(hid)


# ---------------------------------------------------------------- autostart

def launch_agent(program: list[str]) -> dict:
    """A per-user LaunchAgent that starts the app at login."""
    return {"Label": LAUNCH_AGENT_LABEL, "ProgramArguments": program, "RunAtLoad": True,
            "ProcessType": "Interactive"}


def set_autostart(enabled: bool, args: list[str], path: Path = LAUNCH_AGENT) -> None:
    """Start at login with `args` appended to the app's command line."""
    try:
        if enabled:
            frozen = getattr(sys, "frozen", False)
            program = [sys.executable] if frozen else [sys.executable, "-m", "maplehelper"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(plistlib.dumps(launch_agent(program + list(args))))
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass
