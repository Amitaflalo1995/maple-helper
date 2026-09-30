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


# ---------------------------------------------------------------- glass material

class _ACCENT(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]


class _WCAD(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p), ("SizeOfData", ctypes.c_size_t)]


ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
WCA_ACCENT_POLICY = 19


def transparency_enabled() -> bool:
    """Windows 'Transparency effects' setting (the reduced-transparency preference)."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return bool(winreg.QueryValueEx(k, "EnableTransparency")[0])
    except OSError:
        return True


def enable_acrylic(hwnd: int, tint_rgba: tuple[int, int, int, int] = (18, 14, 12, 80)) -> bool:
    """Blur what is behind the window (the game) — the glass material. Returns False if unsupported."""
    try:
        r, g, b, a = tint_rgba
        accent = _ACCENT(ACCENT_ENABLE_ACRYLICBLURBEHIND, 0x20 | 0x40 | 0x80 | 0x100, (a << 24) | (b << 16) | (g << 8) | r, 0)
        data = _WCAD(WCA_ACCENT_POLICY, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p), ctypes.sizeof(accent))
        return bool(user32.SetWindowCompositionAttribute(wt.HWND(hwnd), ctypes.byref(data)))
    except (AttributeError, OSError):
        return False


def round_window(hwnd: int, w: int, h: int, radius: int) -> None:
    """Clip the window (and its blur) to a rounded rectangle."""
    gdi32 = ctypes.windll.gdi32
    rgn = gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, radius * 2, radius * 2)
    user32.SetWindowRgn(wt.HWND(hwnd), rgn, True)


class _BLURBEHIND(ctypes.Structure):
    _fields_ = [("dwFlags", wt.DWORD), ("fEnable", wt.BOOL), ("hRgnBlur", wt.HRGN),
                ("fTransitionOnMaximized", wt.BOOL)]


class _MARGINS(ctypes.Structure):
    _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]


def glass_window(hwnd: int, tint_rgba=(18, 14, 12, 70), shadow: bool = True) -> bool:
    """Acrylic material for a normal (non-layered) frameless window, the way DWM expects it:
    blur-behind on the client area + acrylic accent + rounded corners and a system shadow."""
    ok = False
    try:
        bb = _BLURBEHIND(1, True, None, False)
        dwmapi.DwmEnableBlurBehindWindow(wt.HWND(hwnd), ctypes.byref(bb))
        ok = enable_acrylic(hwnd, tint_rgba)
        pref = ctypes.c_int(2)  # DWMWCP_ROUND
        dwmapi.DwmSetWindowAttribute(wt.HWND(hwnd), 33, ctypes.byref(pref), ctypes.sizeof(pref))
        if shadow:
            m = _MARGINS(-1, -1, -1, -1)
            dwmapi.DwmExtendFrameIntoClientArea(wt.HWND(hwnd), ctypes.byref(m))
    except (AttributeError, OSError):
        return False
    return ok


WDA_EXCLUDEFROMCAPTURE = 0x11


def set_capture_visibility(hwnd: int, visible: bool) -> bool:
    return bool(user32.SetWindowDisplayAffinity(wt.HWND(hwnd), 0 if visible else WDA_EXCLUDEFROMCAPTURE))


def exclude_from_capture(hwnd: int) -> bool:
    """Keep this window out of screen captures: our own backdrop sampling and the
    screenshot sent to Claude then see the game underneath, not the chat."""
    return bool(user32.SetWindowDisplayAffinity(wt.HWND(hwnd), WDA_EXCLUDEFROMCAPTURE))


def grab_screen(x: int, y: int, w: int, h: int):
    """Raw RGB capture of a screen rectangle (physical pixels) → PIL image."""
    with mss.MSS() if hasattr(mss, "MSS") else mss.mss() as s:
        shot = s.grab({"left": x, "top": y, "width": max(1, w), "height": max(1, h)})
    return Image.frombytes("RGB", shot.size, shot.rgb)
