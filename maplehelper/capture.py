"""Screen grabs shared by the Windows and macOS layers (both capture like any screenshot tool)."""
from __future__ import annotations

import io

import mss
from PIL import Image

MAX_SIDE = 1280


def grab_image(x: int, y: int, w: int, h: int) -> Image.Image:
    """RGB capture of a screen rectangle, in mss coordinates (Windows: physical pixels, macOS: points)."""
    with mss.MSS() if hasattr(mss, "MSS") else mss.mss() as s:
        shot = s.grab({"left": x, "top": y, "width": max(1, w), "height": max(1, h)})
    return Image.frombytes("RGB", shot.size, shot.rgb)


def grab_jpeg(rect: tuple[int, int, int, int]) -> bytes:
    """JPEG of a screen rectangle (x, y, w, h), longest side 1280px."""
    img = grab_image(*rect)
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return buf.getvalue()
