"""
For every series in a target category, pull its settled ("finalized")
markets — final traded price plus the actual yes/no result. Resumable:
already-fetched series are skipped on a re-run, so a full ~11,000-series
crawl can be stopped and restarted (it's slow and polite on purpose — see
--sleep).

Run fetch_series.py first.

Usage:
    python scripts/fetch_markets.py                  # everything (slow, ~11k series)
    python scripts/fetch_markets.py --limit-series 500 --seed 1   # bounded sample
    python scripts/fetch_markets.py --categories Politics Elections
"""
import argparse
import json
import random
import time
from pathlib import Path

import requests

BASE = "https://api.elections.kalshi.com/trade-api/v2"
RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
SERIES_FILE = RAW / "series.json"
MARKETS_DIR = RAW / "markets_by_series"

from fetch_series import TARGET_CATEGORIES  # noqa: E402


MAX_RETRIES = 4
MAX_PAGES_PER_SERIES = 25  # 25 * 200 = 5,000 markets - a safety cap, not a real limit


def fetch_settled_markets(series_ticker: str, sleep: float) -> list[dict]:
    """Never loops forever: each page gets at most MAX_RETRIES attempts,
    then this series is skipped (logged, not silently dropped) so one bad
    request can't hang the whole crawl. Also hard-capped at
    MAX_PAGES_PER_SERIES - some series (multivariate combo markets, see
    the MVE filter below) settle so continuously that pagination never
    naturally ends; this is the safety net for whichever ones slip through."""
    out = []
    cursor = None
    for _page in range(MAX_PAGES_PER_SERIES):
        params = {"series_ticker": series_ticker, "status": "settled", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = None
        for attempt in range(MAX_RETRIES):
            if attempt > 0:
                print(f"  ... retrying {series_ticker} (attempt {attempt + 1})", flush=True)
            try:
                r = requests.get(f"{BASE}/markets", params=params, timeout=(5, 8))
            except requests.RequestException as e:
                print(f"  ! {series_ticker}: network error ({e}), "
                      f"attempt {attempt + 1}/{MAX_RETRIES}", flush=True)
                time.sleep(1.0 * (attempt + 1))
                continue
            if r.status_code == 429:
                time.sleep(2.0 * (attempt + 1))
                continue
            if r.status_code >= 500:
                time.sleep(1.0 * (attempt + 1))
                continue
            r.raise_for_status()
            data = r.json()
            break
        if data is None:
            print(f"  x {series_ticker}: giving up after {MAX_RETRIES} attempts, skipping", flush=True)
            break
        out.extend(data.get("markets", []))
        cursor = data.get("cursor")
        if not cursor or not data.get("markets"):
            break
        time.sleep(sleep)
    else:
        print(f"  ! {series_ticker}: hit the {MAX_PAGES_PER_SERIES}-page cap "
              f"({len(out)} markets) - likely a combo series that slipped past "
              f"the MVE filter; truncated, not stuck.", flush=True)
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--categories", nargs="*", default=sorted(TARGET_CATEGORIES))
    p.add_argument("--limit-series", type=int, default=None,
                    help="cap the number of series fetched (for a bounded pilot run)")
    p.add_argument("--seed", type=int, default=0,
                    help="shuffle series before capping, so a bounded run isn't just A-Z bias")
    p.add_argument("--sleep", type=float, default=0.15, help="delay between API calls")
    args = p.parse_args()

    if not SERIES_FILE.exists():
        raise SystemExit("Run scripts/fetch_series.py first.")

    all_series = json.loads(SERIES_FILE.read_text(encoding="utf-8"))
    targets = [s for s in all_series if s.get("category") in args.categories]
    n_before = len(targets)
    # Multivariate/combo series (ticker contains "MVE") settle so continuously
    # they can generate thousands of markets an hour - excluded at the source,
    # not just filtered out downstream, so the crawler doesn't burn its whole
    # run on one series. load_data.py double-checks this at the market level too.
    targets = [s for s in targets if "MVE" not in s.get("ticker", "")]
    if n_before != len(targets):
        print(f"Excluded {n_before - len(targets)} multivariate/combo series (ticker contains 'MVE').")

    if args.seed:
        random.Random(args.seed).shuffle(targets)
    if args.limit_series:
        targets = targets[: args.limit_series]

    MARKETS_DIR.mkdir(parents=True, exist_ok=True)
    already = {f.stem for f in MARKETS_DIR.glob("*.json")}

    fetched, skipped, empty, total_markets = 0, 0, 0, 0
    for i, s in enumerate(targets):
        ticker = s["ticker"]
        safe = ticker.replace("/", "_")
        if safe in already:
            skipped += 1
            continue
        markets = fetch_settled_markets(ticker, args.sleep)
        (MARKETS_DIR / f"{safe}.json").write_text(
            json.dumps({"series_ticker": ticker, "category": s.get("category"),
                        "markets": markets}),
            encoding="utf-8",
        )
        fetched += 1
        total_markets += len(markets)
        if not markets:
            empty += 1
        if fetched % 10 == 0:
            print(f"[{i+1}/{len(targets)}] {fetched} series fetched, "
                  f"{total_markets} settled markets so far ({skipped} already cached)",
                  flush=True)

    print(f"\nDone. {fetched} series fetched this run ({skipped} were already cached), "
          f"{empty} had zero settled markets, {total_markets} settled markets collected.")
