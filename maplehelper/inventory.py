"""Read the in-game inventory from a screenshot: find its slot grid, cut out every item icon and match it to the
knowledge base's item pictures.

The AI couldn't name the items from a screenshot (on a wide screen an icon is a few dozen pixels in a big picture,
seen live). Matching pixels against the database's own icons is exact where the AI guessed: the game draws the
same pictures, only scaled.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

SLOT_BG = np.array([224, 222, 212], np.int16)      # the beige of an inventory slot
SIZE = 24                                            # icons are compared at this size


def _slot_mask(rgb: np.ndarray) -> np.ndarray:
    return (np.abs(rgb.astype(np.int16) - SLOT_BG) <= 14).all(axis=2)


def _runs(row: np.ndarray, lo: int, hi: int) -> list[tuple[int, int]]:
    if not row.any():
        return []
    d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
    s, e = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    return [(int(a), int(b - a)) for a, b in zip(s, e) if lo <= b - a <= hi]


def find_slots(rgb: np.ndarray) -> list[tuple[int, int, int]]:
    """Inventory slots as (x, y, size): rows where three or more equally long, equally spaced beige runs start
    (the top of a row of slots, above the icons), stacked at the same pitch."""
    mask = _slot_mask(rgb)
    best: dict[tuple, list[int]] = {}
    for y in range(mask.shape[0]):
        runs = _runs(mask[y], 24, 200)
        for i in range(len(runs) - 2):
            (x0, n0), (x1, n1), (x2, n2) = runs[i:i + 3]
            pitch = x1 - x0
            if abs(n1 - n0) <= 3 and abs(n2 - n0) <= 3 and abs((x2 - x1) - pitch) <= 3 and pitch - n0 <= n0 // 3:
                # every run of the row on that grid
                xs = [x for x, n in runs if abs(n - n0) <= 3 and (x - x0) % pitch in (0, 1, 2, pitch - 1, pitch - 2)]
                best.setdefault((min(xs) // 4, n0 // 4, pitch // 4), []).append(y)
                break
    if not best:
        return []
    (gx, gn, gp), ys = max(best.items(), key=lambda kv: len(kv[1]))
    n, pitch = gn * 4, gp * 4
    # recover exact numbers from one matching row
    y0 = ys[0]
    runs = [r for r in _runs(mask[y0], 24, 200) if abs(r[1] - n) <= 6]
    if len(runs) < 3:
        return []
    size = int(np.median([r[1] for r in runs]))
    pitch = int(np.median(np.diff([r[0] for r in runs])))
    xs = [r[0] for r in runs]
    # slot tops: the first row of each run of consecutive matching rows
    tops = [y for i, y in enumerate(ys) if i == 0 or y - ys[i - 1] > 2]
    rows = sorted({min(tops) + k * pitch for k in range(round((max(tops) - min(tops)) / pitch) + 1)})
    return [(x, y, size) for y in rows for x in xs if y + size <= rgb.shape[0]]


def _normalise(img: Image.Image, mask: np.ndarray) -> np.ndarray | None:
    """The masked icon cropped to its pixels, on the slot colour, SIZE x SIZE."""
    ys, xs = np.nonzero(mask)
    if len(xs) < 20:
        return None
    box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    a = np.asarray(img.convert("RGB")).astype(np.float32)
    a[~mask] = SLOT_BG
    crop = Image.fromarray(a.astype(np.uint8)).crop(box)
    side = max(crop.size)
    square = Image.new("RGB", (side, side), tuple(int(v) for v in SLOT_BG))
    square.paste(crop, ((side - crop.width) // 2, (side - crop.height) // 2))
    return np.asarray(square.resize((SIZE, SIZE), Image.BILINEAR)).astype(np.float32)


def _icon_vector(path) -> np.ndarray | None:
    try:
        im = Image.open(path).convert("RGBA")
    except OSError:
        return None
    a = np.asarray(im)
    shadow = (a[..., :3].max(axis=2) < 90) & (a[..., 3] < 200)    # the soft drop shadow under some icons
    return _normalise(im, (a[..., 3] > 60) & ~shadow)


_INDEX: dict[str, tuple[list[str], np.ndarray]] = {}


def _index(kb) -> tuple[list[str], np.ndarray]:
    # by folder and size: a KB update keeps the folder but changes its items (a stale key broke describe())
    root = f"{getattr(kb, 'root', '')}|{len(kb.entities)}|{id(kb)}"
    if root not in _INDEX:
        _INDEX.clear()
        keys, vecs = [], []
        for k, e in kb.entities.items():
            if e.get("category") != "item":
                continue
            path = kb.image_path(k)
            v = _icon_vector(path) if path else None
            if v is not None:
                keys.append(k)
                vecs.append(v)
        _INDEX[root] = (keys, np.stack(vecs) if vecs else np.zeros((0, SIZE, SIZE, 3), np.float32))
    return _INDEX[root]


@dataclass
class Slot:
    index: int                      # 1-based, left to right, top to bottom
    picture: bytes                  # the icon as the game shows it (PNG)
    matches: list[tuple[str, float]] = field(default_factory=list)   # (item key, distance), best first


def warm(kb) -> None:
    """Build the icon index ahead of time (2,700 pictures, ~1 s): the first inventory check doesn't wait."""
    _index(kb)


def read(img: Image.Image, kb, top: int = 3) -> list[Slot]:
    """Every filled slot of the inventory in a full-resolution screenshot, with its best database matches."""
    rgb = np.asarray(img.convert("RGB"))
    keys, vecs = _index(kb)
    out = []
    for i, (x, y, size) in enumerate(find_slots(rgb), 1):
        cell = img.crop((x, y, x + size, y + size))
        c = np.asarray(cell.convert("RGB")).astype(np.int16)
        edge = max(3, size // 12)
        if _slot_mask(c[:edge]).mean() < 0.6 or min(_slot_mask(c[:, :edge]).mean(), _slot_mask(c[:, -edge:]).mean()) < 0.8:
            continue                 # not a whole slot (the last row is cut by the window's edge)
        if c.reshape(-1, 3).std(axis=0).max() < 20:
            continue                 # an empty slot: just the speckled beige
        dark_shadow = (np.abs(c - c.mean(axis=2, keepdims=True)) < 10).all(axis=2) & (c.max(axis=2) < 200) & \
            (c.max(axis=2) > 60)
        mask = ~_slot_mask(c) & ~dark_shadow & ~((c >= 232).all(axis=2))
        if mask.mean() < 0.04:
            continue                 # an empty slot
        v = _normalise(cell, mask)
        if v is None:
            continue
        buf = io.BytesIO()
        cell.save(buf, "PNG")
        slot = Slot(i, buf.getvalue())
        if len(keys):
            d = np.abs(vecs - v).mean(axis=(1, 2, 3))
            order = np.argsort(d)[:top]
            slot.matches = [(keys[j], float(d[j])) for j in order]
        out.append(slot)
    return out


def describe(slots: list[Slot], kb) -> str:
    """The reading for the AI: per slot, the likely items (closest first)."""
    lines = []
    for s in slots:
        names = ", ".join(f"{kb.get(k)['name']} [{k}]" for k, _ in s.matches if kb.get(k))
        lines.append(f"Slot {s.index}: {names or 'unknown'}")
    return "\n".join(lines)
