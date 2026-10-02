"""Items a player is hunting for, per character: who drops them, and a heads-up when the KB changes them."""
from __future__ import annotations


def items(settings, cid: str | None) -> list[str]:
    return list((settings["wishlist"] or {}).get(cid or "", []))


def toggle(settings, cid: str | None, key: str) -> bool:
    """Add or remove; returns True when the item is now on the list."""
    if not cid:
        return False
    data = dict(settings["wishlist"] or {})
    keys = list(data.get(cid, []))
    wished = key not in keys
    keys = keys + [key] if wished else [k for k in keys if k != key]
    data[cid] = keys
    settings["wishlist"] = data
    return wished


def touched(entries: list[dict], keys: list[str], kb) -> list[str]:
    """Names of wished items that a KB update added, removed, changed, or whose drops changed."""
    names = {k: (kb.get(k) or {}).get("name") for k in keys}
    wanted = {n for n in names.values() if n}
    hit: list[str] = []

    def add(name):
        if name and name not in hit:
            hit.append(name)
    for e in entries:
        for kind in ("added", "removed", "changed", "updated"):
            for r in (e.get(kind) or []) if isinstance(e, dict) else []:
                if not isinstance(r, dict):
                    continue
                if r.get("key") in names:
                    add(r.get("name"))
                for item in (r.get("drops_added") or []) + (r.get("drops_removed") or []):
                    if item in wanted:
                        add(item)
    return hit
