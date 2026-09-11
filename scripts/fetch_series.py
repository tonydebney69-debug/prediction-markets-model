"""
Fetch Kalshi's full series catalogue (a "series" is a recurring market
template — e.g. "Fed meeting rate decision" — under which individual dated
markets settle). Public, unauthenticated, documented API:
https://trading-api.readme.io/reference/getseries

Kalshi is used here instead of Polymarket because Polymarket is blocked at
the network level in Australia (resolves to an ACMA block page) — see
README "Data source" for the full story.

Usage:
    python scripts/fetch_series.py
"""
import json
import time
from pathlib import Path

import requests

BASE = "https://api.elections.kalshi.com/trade-api/v2"
RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
OUT = RAW / "series.json"

# Categories with a real behavioural/information story — the kind of thing
# the favourite-longshot literature is actually about. Financials, Crypto
# and Commodities are excluded: those are binary options on liquid,
# efficiently-arbitraged assets, a different animal from an event market.
TARGET_CATEGORIES = {
    "Politics", "Elections", "Sports", "Entertainment", "Economics",
    "Mentions", "Climate and Weather", "Science and Technology", "World",
    "Health", "Social", "Transportation", "Exotics",
}


def fetch_all_series() -> list[dict]:
    all_series = []
    cursor = None
    while True:
        params = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
        r = requests.get(f"{BASE}/series", params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        all_series.extend(data.get("series", []))
        cursor = data.get("cursor")
        if not cursor or not data.get("series"):
            break
        time.sleep(0.1)
    return all_series


if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    series = fetch_all_series()
    OUT.write_text(json.dumps(series), encoding="utf-8")

    by_cat: dict[str, int] = {}
    for s in series:
        by_cat[s.get("category", "?")] = by_cat.get(s.get("category", "?"), 0) + 1

    print(f"{len(series)} series total, saved to {OUT}\n")
    for cat, n in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        flag = "  <- target" if cat in TARGET_CATEGORIES else ""
        print(f"  {cat:24s} {n:6d}{flag}")

    n_target = sum(n for c, n in by_cat.items() if c in TARGET_CATEGORIES)
    print(f"\n{n_target} series in target (non-financial) categories.")
