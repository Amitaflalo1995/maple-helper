"""Screen grabs shared by the Windows and macOS layers (both capture like any screenshot tool)."""
from __future__ import annotations

import io

import mss
from PIL import Image

# the most the AI takes in without shrinking it again: on a 3440 px ultrawide, 1280 left inventory icons
# ~12 px wide and the AI couldn't tell them apart (live test)
MAX_SIDE = 1568
# the latest grab at full resolution: the portrait is cut from it (a name tag is ~10 px tall at that size)
LAST_FULL: Image.Image | None = None
# where the mouse was in that grab (image pixels): the game draws its own hand cursor, and over an inventory
# slot it looked like an item (live test)
LAST_CURSOR: tuple[int, int] | None = None


def _cursor_in(x: int, y: int, w: int, h: int) -> tuple[int, int] | None:
    import sys
    if sys.platform != "win32":
        return None
    import ctypes
    import ctypes.wintypes as wt
    p = wt.POINT()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(p)):
        return None
    return (p.x - x, p.y - y) if 0 <= p.x - x < w and 0 <= p.y - y < h else None


def grab_image(x: int, y: int, w: int, h: int) -> Image.Image:
    """RGB capture of a screen rectangle, in mss coordinates (Windows: physical pixels, macOS: points)."""
    with mss.MSS() if hasattr(mss, "MSS") else mss.mss() as s:
        shot = s.grab({"left": x, "top": y, "width": max(1, w), "height": max(1, h)})
    return Image.frombytes("RGB", shot.size, shot.rgb)


def detail_tiles(img: Image.Image | None, width: int = 1200) -> list[bytes]:
    """The latest grab at full resolution, cut left to right into tiles the AI reads without shrinking them:
    small things (inventory icons) stay legible on a wide screen. Nothing when the grab is small already."""
    if img is None or max(img.size) <= MAX_SIDE:
        return []
    n = -(-img.width // width)
    step = img.width / n
    tiles = []
    for i in range(n):
        left, right = max(0, int(i * step) - 40), min(img.width, int((i + 1) * step) + 40)   # a little overlap
        tile = img.crop((left, 0, right, img.height))
        tile.thumbnail((MAX_SIDE, MAX_SIDE))
        buf = io.BytesIO()
        tile.save(buf, "JPEG", quality=85)
        tiles.append(buf.getvalue())
    return tiles


def grab_jpeg(rect: tuple[int, int, int, int]) -> bytes:
    """JPEG of a screen rectangle (x, y, w, h), longest side MAX_SIDE."""
    global LAST_FULL, LAST_CURSOR
    img = grab_image(*rect)
    LAST_FULL = img.copy()
    try:
        LAST_CURSOR = _cursor_in(*rect)
    except Exception:      # noqa: BLE001
        LAST_CURSOR = None
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return buf.getvalue()
