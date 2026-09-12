"""
Fixes finding #2 from the pilot: many Sports series are exhaustive,
single-winner fields (one market per entrant, exactly one resolves yes)
split into separate binary contracts - e.g. "will driver X have the
fastest lap?" repeated once per driver in the race. Pooling those by raw
price without normalising within the field is the same mistake as reading
horse-racing odds without removing the overround: of course the average
"implied price" runs above the average "actual yes rate" when N entrants'
prices are each priced as if only they mattered, not as a field that has
to sum to ~100%.

Not every multi-market Sports event is this kind of field, though - e.g.
total-runs-over/under ladders (over 3.5, over 4.5, over 5.5 in the same
game) are NESTED, not mutually exclusive: several can resolve yes at once.
Forcing those into a horse-racing-style normalisation would be wrong in
the other direction. So this script classifies each series empirically
before touching anything:

    For every series with enough multi-market events (>=3 markets),
    look at how many of its markets actually resolved "yes" per event,
    across all its events:
        - ~always exactly 1 yes per event  -> exhaustive field, normalise
        - anything messier (0, 2, 3+ commonly) -> leave alone

Usage:
    python scripts/event_field_normalization.py --set discovery
"""
import argparse
from pathlib import Path

import pandas as pd

PROCESSED = Path(__file__).resolve().parent.parent / "data" / "processed"

MIN_EVENTS_TO_CLASSIFY = 3   # need at least this many multi-market events to trust the pattern
MIN_FIELD_SIZE = 3           # events with only 1-2 markets are trivial complements, skip
EXHAUSTIVE_EXACTLY1_THRESHOLD = 0.90
EXHAUSTIVE_GT1_THRESHOLD = 0.05


def classify_series(df: pd.DataFrame) -> pd.DataFrame:
    """One row per series_ticker: is it an exhaustive single-winner field?"""
    rows = []
    for st, sub in df.groupby("series_ticker"):
        ev = sub.groupby("event_ticker").agg(n=("ticker", "size"), yes=("won_yes", "sum"))
        ev = ev[ev["n"] >= MIN_FIELD_SIZE]
        if len(ev) < MIN_EVENTS_TO_CLASSIFY:
            continue
        frac_exactly1 = (ev["yes"] == 1).mean()
        frac_gt1 = (ev["yes"] > 1).mean()
        exhaustive = frac_exactly1 >= EXHAUSTIVE_EXACTLY1_THRESHOLD and frac_gt1 <= EXHAUSTIVE_GT1_THRESHOLD
        rows.append({"series_ticker": st, "n_events": len(ev),
                     "median_field_size": ev["n"].median(),
                     "frac_exactly1": round(frac_exactly1, 3),
                     "frac_gt1": round(frac_gt1, 3), "exhaustive": exhaustive})
    return pd.DataFrame(rows)


def apply_normalization(df: pd.DataFrame, classification: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    exhaustive_series = set(classification.loc[classification["exhaustive"], "series_ticker"])
    df["is_exhaustive_field"] = df["series_ticker"].isin(exhaustive_series)

    # only normalise within events that actually have a real field (>=3 markets);
    # a 2-market or singleton "event" under an exhaustive series is already fine as-is
    field_size = df.groupby("event_ticker")["ticker"].transform("size")
    do_normalize = df["is_exhaustive_field"] & (field_size >= MIN_FIELD_SIZE)

    field_sum = df.groupby("event_ticker")["implied_p"].transform("sum")
    df["field_normalized_p"] = df["implied_p"]
    df.loc[do_normalize, "field_normalized_p"] = (
        df.loc[do_normalize, "implied_p"] / field_sum[do_normalize]
    )
    return df


def calibration_table(df: pd.DataFrame, price_col: str, n_buckets: int = 6) -> pd.DataFrame:
    d = df[(df[price_col] > 0.02) & (df[price_col] < 0.98)].copy()
    d["bucket"] = pd.qcut(d[price_col], n_buckets, duplicates="drop")
    g = d.groupby("bucket", observed=True)
    out = pd.DataFrame({
        "n": g.size(),
        "avg_implied_pct": (g[price_col].mean() * 100).round(1),
        "actual_yes_pct": (g["won_yes"].mean() * 100).round(1),
    })
    out["edge_pts"] = (out["actual_yes_pct"] - out["avg_implied_pct"]).round(1)
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--set", choices=["discovery", "holdout"], default="discovery")
    args = p.parse_args()

    df = pd.read_parquet(PROCESSED / f"{args.set}.parquet")
    sports = df[df["category"] == "Sports"]

    classification = classify_series(sports)
    n_exhaustive = classification["exhaustive"].sum()
    print(f"{len(classification)} Sports series had enough multi-market events to classify; "
          f"{n_exhaustive} are exhaustive single-winner fields.\n")
    print("Exhaustive fields found:")
    print(classification[classification["exhaustive"]]
          .sort_values("n_events", ascending=False)
          [["series_ticker", "n_events", "median_field_size"]].to_string(index=False))
    print("\nLeft alone (not exhaustive - nested thresholds or genuinely independent props):")
    print(classification[~classification["exhaustive"]]
          .sort_values("n_events", ascending=False)
          [["series_ticker", "n_events", "median_field_size", "frac_gt1"]]
          .head(10).to_string(index=False))

    normed = apply_normalization(df, classification)

    print("\n=== Sports, mid-range (2c-98c), BEFORE normalisation (raw last price) ===")
    before = calibration_table(normed[normed["category"] == "Sports"], "implied_p")
    print(before.to_string())

    print("\n=== Sports, mid-range (2c-98c), AFTER field normalisation ===")
    after = calibration_table(normed[normed["category"] == "Sports"], "field_normalized_p")
    print(after.to_string())

    n_touched = normed["is_exhaustive_field"].sum()
    print(f"\n{n_touched:,} of {len(normed[normed['category']=='Sports']):,} Sports rows "
          f"belonged to an exhaustive field and had their price renormalised.")
