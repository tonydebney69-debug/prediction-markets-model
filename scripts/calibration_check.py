"""
The prediction-market equivalent of the horse-racing project's
favourite_longshot_bias.py: does the market's own implied probability
(last traded price) match how often the thing actually happens?

Literature on Polymarket has found a real favourite-longshot bias there
(long-shot "yes" contracts overpriced relative to how often they resolve
yes). Polymarket itself is blocked at the network level in Australia (see
README), so this uses Kalshi instead - a CFTC-regulated exchange with a
different user base (real-money, KYC'd, arguably more professional than
Polymarket's crypto-native retail crowd). Whether Kalshi shows the same
bias is an open question this script is built to answer, not assume.

Kalshi trading fee, applied here as the realistic cost (public formula):
    fee = ceil_to_cent(0.07 * contracts * price * (1 - price))
Highest around 50c, near zero at the extremes - the opposite cost shape to
Betfair's flat commission, and worth keeping in mind when reading results.

Run on --set discovery while exploring; --set holdout only once, after a
method is fully frozen on discovery alone.
"""
import argparse
import math
from pathlib import Path

import pandas as pd

PROCESSED = Path(__file__).resolve().parent.parent / "data" / "processed"


def kalshi_fee(price: pd.Series, contracts: float = 1.0) -> pd.Series:
    raw = 0.07 * contracts * price * (1 - price)
    return (raw * 100).apply(math.ceil) / 100.0


def load(which: str) -> pd.DataFrame:
    df = pd.read_parquet(PROCESSED / f"{which}.parquet")
    df = df[(df["implied_p"] > 0) & (df["implied_p"] < 1)].copy()
    return df


def calibration_table(df: pd.DataFrame, n_buckets: int = 10) -> pd.DataFrame:
    df = df.copy()
    df["bucket"] = pd.qcut(df["implied_p"], n_buckets, labels=False, duplicates="drop")
    g = df.groupby("bucket")
    out = pd.DataFrame({
        "n": g.size(),
        "avg_implied_price_c": (g["implied_p"].mean() * 100).round(1),
        "actual_yes_pct": (g["won_yes"].mean() * 100).round(1),
    })
    out["edge_pct_pts"] = (out["actual_yes_pct"] - out["avg_implied_price_c"]).round(2)

    # flat $1-notional "buy yes at last price" return, before and after fee
    stake = 1.0
    contracts = stake / df["implied_p"]  # $1 worth of "yes" contracts at that price
    gross = contracts * (df["won_yes"] * (1 - df["implied_p"]) - (1 - df["won_yes"]) * df["implied_p"])
    fee = kalshi_fee(df["implied_p"], contracts)
    out["roi_pct_gross"] = (df.assign(g=gross).groupby("bucket")["g"].sum() / stake / g.size() * 100).round(2)
    net = gross - fee
    out["roi_pct_net_of_fee"] = (df.assign(n=net).groupby("bucket")["n"].sum() / stake / g.size() * 100).round(2)
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--set", choices=["discovery", "holdout"], default="discovery")
    p.add_argument("--buckets", type=int, default=10)
    p.add_argument("--category", default=None, help="restrict to one category, e.g. Politics")
    args = p.parse_args()

    df = load(args.set)
    if args.category:
        df = df[df["category"] == args.category]

    print(f"{args.set}: {len(df):,} settled markets"
          + (f" in {args.category}" if args.category else " across all target categories"))
    print(f"date range: {df['close_time'].min()} -> {df['close_time'].max()}\n")

    extreme = ((df["implied_p"] <= 0.02) | (df["implied_p"] >= 0.98)).mean()
    if extreme > 0.5:
        print(f"WARNING: {extreme:.0%} of this sample has a last price at or beyond 2c/98c.\n"
              "That's expected for fast-resolving markets where the last trade happens after\n"
              "the outcome is effectively known - see README 'Findings #1'. The bucket table\n"
              "below will be dominated by these near-certain contracts; read it with that in\n"
              "mind, and see --category plus the README for the cleaner uncertain-price subset.\n")
    if not args.category:
        sports_share = (df["category"] == "Sports").mean()
        if sports_share > 0.3:
            print(f"WARNING: {sports_share:.0%} of this sample is Sports. Many Sports markets are\n"
                  "one-of-many-entrant fields (e.g. per-driver 'fastest lap') split into separate\n"
                  "binary contracts, not independent yes/no propositions - pooling them by price\n"
                  "without grouping by event first will look like bias that isn't there. See\n"
                  "README 'Findings #2' before trusting any pooled Sports number.\n")

    print("Bucket 0 = cheapest 'yes' (market thinks unlikely) ... "
          f"bucket {args.buckets - 1} = most expensive 'yes' (market thinks likely)\n")
    print(calibration_table(df, args.buckets).to_string())

    print("\n--- by category (all price levels pooled) ---")
    by_cat = []
    for cat, g in df.groupby("category"):
        if len(g) < 200:
            continue
        by_cat.append({
            "category": cat, "n": len(g),
            "avg_implied_pct": round(g["implied_p"].mean() * 100, 1),
            "actual_yes_pct": round(g["won_yes"].mean() * 100, 1),
        })
    print(pd.DataFrame(by_cat).sort_values("n", ascending=False).to_string(index=False))
