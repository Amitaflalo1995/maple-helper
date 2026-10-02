"""Prices: what an NPC pays and charges (the KB's item pages) and what players ask on the Free Market
(NiaMeowDB's player-reported listings, the same public endpoint its Free Market page reads)."""
from __future__ import annotations

import json
import re
import statistics
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

FM_URL = "https://meowdb.com/msclassic/api/market-listings/browse"
FM_PAGE = "https://meowdb.com/msclassic/free-market"
UA = "Maple Helper (https://github.com/Amitaflalo1995/maple-helper)"
CACHE_SECONDS = 600
_cache: dict[str, tuple[float, dict | None]] = {}


@dataclass
class NpcPrices:
    sell_back: int | None                       # what an NPC pays you
    shops: list[tuple[str, str, int]] = field(default_factory=list)   # (NPC, where, price), cheapest first
    unpriced: list[tuple[str, str]] = field(default_factory=list)     # (NPC, where): sells it, no price in the page
    ranks: dict[tuple[str, str], str] = field(default_factory=dict)   # (NPC, where) -> citizen grade its price needs


def _int(text: str) -> int | None:
    m = re.search(r"[\d,]+", text or "")
    return int(m.group(0).replace(",", "")) if m else None


# the price line under a town shop: "COT2 prices Citizen of Honor +" (that citizen grade and up; the KB's item pages,
# e.g. pages/item/274.md, Max City General Store), or a bare "COT2 prices"
_RANK = re.compile(r"^COT2 prices\s+(.+?)\s*\+?\s*$")


def npc_prices(kb, key: str) -> NpcPrices:
    lines = [ln.strip() for ln in kb.page(key).split("\n---", 2)[-1].splitlines()]
    sell = next((_int(ln) for ln in lines if ln.startswith("NPC Sell-back")), None)
    out = NpcPrices(sell)
    if "Where to buy" in lines:
        i = lines.index("Where to buy") + 1
        # blocks of: "<NPC> <role> [cheapest]" / "<map> · <town>" / "<price>" / "mesos" [/ "COT2 prices [grade +]"]
        # the price is "-" for a few NPCs the page lists without one (pages/item/241.md: Jane, Lith Harbor)
        while i + 3 < len(lines) and lines[i + 3] == "mesos":
            npc = re.sub(r"\s+cheapest$", "", lines[i]).strip()
            where, price = lines[i + 1], _int(lines[i + 2])
            if price is not None:
                out.shops.append((npc, where, price))
            elif npc:
                out.unpriced.append((npc, where))
            nxt = lines[i + 4] if i + 4 < len(lines) else ""
            rank = _RANK.match(nxt)
            if rank:
                out.ranks[(npc, where)] = rank.group(1)
            i += 5 if nxt.startswith("COT2") else 4
    out.shops.sort(key=lambda s: s[2])
    return out


@dataclass
class Market:
    count: int
    median: int | None = None
    low: int | None = None
    high: int | None = None
    latest: float | None = None                 # unix time of the newest report


def summarize(rows: list[dict], name: str) -> Market:
    prices, times = [], []
    for r in rows:
        if not isinstance(r, dict) or str(r.get("itemName") or "").strip().lower() != name.strip().lower():
            continue                            # the search is "contains": keep this exact item
        each = r.get("priceEach") or r.get("price")
        if isinstance(each, (int, float)) and each > 0:
            prices.append(int(each))
        t = r.get("createdAt")
        if isinstance(t, (int, float)):
            times.append(t / 1000 if t > 1e11 else t)
        elif isinstance(t, str):
            try:
                from datetime import datetime
                times.append(datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp())
            except ValueError:
                pass
    if not prices:
        return Market(0)
    return Market(len(prices), int(statistics.median(prices)), min(prices), max(prices), max(times) if times else None)


def free_market(name: str, timeout: float = 10) -> Market | None:
    """Player listings for an item (sell side, last 14 days). None when the site can't be reached."""
    hit = _cache.get(name.lower())
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    url = FM_URL + "?" + urllib.parse.urlencode({"q": name, "sort": "price_low"})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    rows = data.get("rows") if isinstance(data, dict) else None
    out = summarize(rows if isinstance(rows, list) else [], name)
    _cache[name.lower()] = (time.time(), out)
    return out


def page_url(name: str) -> str:
    return FM_PAGE + "?" + urllib.parse.urlencode({"q": name})
