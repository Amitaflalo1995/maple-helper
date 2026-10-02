"""The character portrait: find the player's name tag in a screenshot and crop the sprite standing on it.

The AI's avatar_box is only a rough pointer: on a wide screen its fractions were off by a sprite or more (live test:
an NPC, a treetop, a sprite cut in half). A name tag is easy to find with plain pixels: a translucent dark plate with
white letters, right under the character's feet. The plate darkens whatever is behind it by the same factor, so its
top and bottom edges are straight lines where the brightness drops (and comes back) by that factor. The sprite is
about five tag-heights tall, centred on the tag.
"""
from __future__ import annotations

import numpy as np


def _runs(row: np.ndarray, lo: int = 30, hi: int = 420) -> list[tuple[int, int]]:
    """(start, length) of the runs of True in a 1-D bool array, lo <= length <= hi."""
    if not row.any():
        return []
    d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    return [(int(s), int(e - s)) for s, e in zip(starts, ends) if lo <= e - s <= hi]


def find_name_tags(rgb: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Name-tag plates in an RGB array: [(x, y, w, h)]."""
    f = rgb.astype(np.float32)
    luma = f[..., 0] * 0.3 + f[..., 1] * 0.59 + f[..., 2] * 0.11 + 1.0
    ratio = luma[1:] / luma[:-1]                       # ratio[y] = row y+1 against row y
    white = (f.min(axis=2) >= 225) & (f.max(axis=2) - f.min(axis=2) < 30)
    tops = {y + 1: _runs((ratio[y] > 0.22) & (ratio[y] < 0.65)) for y in range(ratio.shape[0])}
    bottoms = {y: _runs((ratio[y] > 1.5) & (ratio[y] < 4.5)) for y in range(ratio.shape[0])}
    found = []
    for y0, runs in tops.items():
        for x0, n in runs:
            for h in range(9, 61):
                y1 = y0 + h - 1                        # the plate's last row
                if y1 not in bottoms:
                    break
                if any(abs(bx - x0) <= 5 and abs(bn - n) <= 10 for bx, bn in bottoms[y1]):
                    letters = white[y0:y1 + 1, x0:x0 + n].mean()
                    if 2.2 <= n / h <= 14 and 0.04 <= letters <= 0.5:
                        found.append((x0, y0, n, h))
                    break
    return found


def portrait_rect(rgb: np.ndarray, box: list[float] | None) -> tuple[int, int, int, int] | None:
    """Pixel rect (left, top, right, bottom) of the player's sprite, from the AI's rough box (fractions).
    Without a box, only when the screenshot has exactly one name tag (just the player in sight)."""
    H, W = rgb.shape[:2]
    if box is None:
        tags = find_name_tags(rgb)
        if len(tags) != 1:
            return None
        tx, ty, tw, th = tags[0]
        box = [tx / W, (ty - th * 5) / H, tw / W, th * 5 / H]
    x, y, w, h = box
    # look around the AI's box: the tag is under the feet, and the box itself may be off by a sprite or two
    cx, cy = (x + w / 2) * W, (y + h / 2) * H
    rw, rh = max(w * W * 3, W * 0.06), max(h * H * 2.5, H * 0.12)
    left, top = int(max(0, cx - rw)), int(max(0, cy - rh))
    right, bottom = int(min(W, cx + rw)), int(min(H, cy + rh * 1.4))
    tags = find_name_tags(rgb[top:bottom, left:right])
    if not tags:
        # the box was further off than that (live test: it pointed at a TAXI sign 400 px away): every tag on screen,
        # nearest to the box (other players have tags too, NPCs don't: theirs are opaque yellow plates)
        tags, left, top = find_name_tags(rgb), 0, 0
        if not tags:
            return None
    fx, fy = cx - left, (y + h) * H - top           # the box's feet
    tx, ty, tw, th = min(tags, key=lambda t: (t[0] + t[2] / 2 - fx) ** 2 + (t[1] - fy) ** 2)
    side = int(th * 5.4)
    mid = left + tx + tw / 2
    feet = top + ty
    rect = (int(mid - side / 2), feet - side, int(mid + side / 2), feet + int(th * 0.2))
    if rect[0] < 0 or rect[1] < 0 or rect[2] > W:
        return None
    return rect
