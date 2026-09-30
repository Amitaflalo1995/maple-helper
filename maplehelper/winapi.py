"""Small Windows helpers: find the game window, capture it, focus handling, key state.

Deliberately non-invasive: no keyboard hooks, no process access. The game window
is found by its title and captured from the screen like any screenshot tool.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import io

import mss
from PIL import Image

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi

GAME_TITLES = ("MapleStory Classic", "MapleStory", "Classic World")
VK = {f"F{i}": 0x6F + i for i in range(1, 13)}   # F1=0x70 ... F12=0x7B
MAX_SIDE = 1280

EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def _title(hwnd) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def find_game_window() -> int | None:
    found: list[int] = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            t = _title(hwnd)
            if any(g.lower() in t.lower() for g in GAME_TITLES) and "maple helper" not in t.lower():
                found.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found[0] if found else None


def window_rect(hwnd) -> tuple[int, int, int, int] | None:
    """Visible bounds (without the invisible resize border)."""
    r = wt.RECT()
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
    w, h = r.right - r.left, r.bottom - r.top
    return (r.left, r.top, w, h) if w > 50 and h > 50 else None


def capture_game(hwnd: int | None = None) -> bytes | None:
    """JPEG of the game window (longest side 1280px), or None if the game isn't found."""
    hwnd = hwnd or find_game_window()
    if not hwnd:
        return None
    rect = window_rect(hwnd)
    if not rect:
        return None
    x, y, w, h = rect
    with mss.MSS() if hasattr(mss, "MSS") else mss.mss() as s:
        shot = s.grab({"left": x, "top": y, "width": w, "height": h})
    img = Image.frombytes("RGB", shot.size, shot.rgb)
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def is_exclusive_fullscreen(hwnd: int | None) -> bool:
    """Best-effort: a window covering its monitor with no Borderless flag set by the game.

    True exclusive fullscreen can't be detected reliably from outside; the overlay
    shows a hint only when it failed to appear over a covering window.
    """
    return False


def foreground_window() -> int:
    return user32.GetForegroundWindow()


def focus_window(hwnd: int) -> None:
    if hwnd and user32.IsWindow(hwnd):
        user32.SetForegroundWindow(hwnd)


def key_down(key_name: str) -> bool:
    vk = VK.get(key_name)
    return bool(vk and user32.GetAsyncKeyState(vk) & 0x8000)


MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312


def register_hotkey(hwnd: int, hotkey_id: int, key_name: str) -> bool:
    vk = VK.get(key_name)
    return bool(vk and user32.RegisterHotKey(wt.HWND(hwnd), hotkey_id, MOD_NOREPEAT, vk))


def unregister_hotkey(hwnd: int, hotkey_id: int) -> None:
    user32.UnregisterHotKey(wt.HWND(hwnd), hotkey_id)
