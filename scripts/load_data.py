"""
Combine the per-series JSON files into one clean table, then split into
discovery and holdout by close date — same discipline as the horse-racing
project: explore and tune on discovery only, holdout gets one honest look
at the end, after a method is fully specified.

Unlike a horse race (one winner among many runners, so prices need
overround-normalising to get a fair implied probability), each Kalshi
market is an independent yes/no contract that settles at $1 or $0 — the
last traded price in dollars *is* the market's implied probability
already, no normalisation needed.

Usage:
    python scripts/load_data.py --holdout-months 3
"""
import argparse
import json
from pathlib import Path

import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "markets_by_series"
PROCESSED = Path(__file__).resolve().parent.parent / "data" / "processed"

FIELDS = [
    "ticker", "event_ticker", "title", "yes_sub_title", "open_time",
    "close_time", "result", "status", "last_price_dollars",
    "yes_bid_dollars", "yes_ask_dollars", "volume_fp", "open_interest_fp",
    "market_type",
]


def load_all() -> pd.DataFrame:
    files = sorted(RAW.glob("*.json"))
    if not files:
        raise SystemExit(f"No files in {RAW} — run fetch_series.py then fetch_markets.py first.")
    rows = []
    for f in files:
        blob = json.loads(f.read_text(encoding="utf-8"))
        cat = blob.get("category")
        series_ticker = blob.get("series_ticker")
        for m in blob.get("markets", []):
            # skip multivariate/combo markets - a different, arbitrage-priced
            # animal, not the behavioural-bias story this project is testing
            if "MVE" in m.get("event_ticker", "") or m.get("market_type") != "binary":
                continue
            row = {k: m.get(k) for k in FIELDS}
            row["series_ticker"] = series_ticker
            row["category"] = cat
            rows.append(row)
    df = pd.DataFrame(rows)
    df = df[df["result"].isin(["yes", "no"])].copy()
    df["open_time"] = pd.to_datetime(df["open_time"], errors="coerce", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], errors="coerce", utc=True)
    df = df.dropna(subset=["close_time", "last_price_dollars"])
    df["won_yes"] = (df["result"] == "yes").astype(int)
    df["implied_p"] = df["last_price_dollars"].astype(float)
    df["year_month"] = df["close_time"].dt.to_period("M")
    return df


def split(df: pd.DataFrame, holdout_months: int):
    months = sorted(df["year_month"].dropna().unique())
    if len(months) <= holdout_months:
        raise SystemExit(f"Only {len(months)} months of data - reduce --holdout-months or fetch more.")
    cutoff = months[-holdout_months]
    discovery = df[df["year_month"] < cutoff].copy()
    holdout = df[df["year_month"] >= cutoff].copy()
    return discovery, holdout


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--holdout-months", type=int, default=3)
    args = p.parse_args()

    PROCESSED.mkdir(parents=True, exist_ok=True)
    df = load_all()
    discovery, holdout = split(df, args.holdout_months)

    discovery.to_parquet(PROCESSED / "discovery.parquet", index=False)
    holdout.to_parquet(PROCESSED / "holdout.parquet", index=False)

    print(f"total markets:  {len(df):,}")
    print(f"discovery:      {len(discovery):,} rows, "
          f"{discovery['year_month'].min()} -> {discovery['year_month'].max()}")
    print(f"holdout:        {len(holdout):,} rows, "
          f"{holdout['year_month'].min()} -> {holdout['year_month'].max()}  (untouched)")
    print("\nby category (discovery):")
    print(discovery["category"].value_counts().to_string())
