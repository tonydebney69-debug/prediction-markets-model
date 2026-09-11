# prediction-markets-model

A quantitative look at prediction markets, built with the same discipline as
[`coinbase-momentum-bot`](../coinbase-momentum-bot) and
[`horse-racing-model`](../horse-racing-model): measure first, distrust
anything that looks good on the first pass, hold out a window and don't
touch it until a method is fully frozen.

**The question:** the horse-racing project found Betfair's Australian
exchange to be a genuinely efficient market — three separate tests of its
pricing found nothing to exploit. Prediction markets are much younger and
thinner. Does the same "well-calibrated, no edge" result hold here, or is
this a market still inefficient enough to have something in it?

## Data source — and why it's Kalshi, not Polymarket

Polymarket is the obvious first choice — huge volume, well-studied, and
academic work has found a real favourite-longshot bias there (long-shot
"yes" contracts overpriced relative to how often they resolve yes).

**It's not reachable from here.** `polymarket.com` and its API
(`gamma-api.polymarket.com`) resolve to an IP that returns a certificate for
`block.acma.gov.au` — the Australian Communications and Media Authority's
block page for unlicensed offshore wagering services. This isn't a terms-
of-service question the way the racing sites were; it's a network-level
block in this country. Worth knowing on its own: prediction markets are
being treated as wagering, not information markets, at the regulatory
level here.

**Used instead: [Kalshi](https://kalshi.com)**, a US, CFTC-regulated
exchange, via its public, documented, unauthenticated market-data API
(`api.elections.kalshi.com` — the base URL is a historical name from
Kalshi's election-market roots; it now serves all categories). This is a
real, intentional developer API, not something reverse-engineered — no
ToS ambiguity like the racing sites.

**The honest caveat this creates:** Kalshi's user base is real-money, KYC'd,
US-based, and arguably more professional than Polymarket's crypto-native,
pseudonymous, global retail crowd. A bias found on Polymarket is not
assumed to exist on Kalshi — that's exactly what this project tests rather
than takes on faith.

Kalshi lists ~14,000 "series" (recurring market templates, e.g. "Fed
meeting rate decision", under which dated markets settle) across many
categories. This project uses the non-financial ones:

| Included (behavioural/information markets) | Excluded (efficiently arbitraged) |
|---|---|
| Politics, Elections, Sports, Entertainment, Economics, Mentions, Climate and Weather, Science and Technology, World, Health, Social, Transportation, Exotics | Financials, Crypto, Commodities |

The excluded categories are binary options on liquid, continuously-priced
assets (BTC, S&P, FX) — arbitraged against the underlying, not a
behavioural story, and a different research question from "does the crowd
misjudge how likely an event is."

Each settled market gives:
- `last_price_dollars` — the final traded price. Because a Kalshi contract
  settles at exactly $1 (yes) or $0 (no), the last price **is** the
  market's implied probability directly — no overround-normalising needed
  the way a multi-runner horse race requires.
- `result` — the actual yes/no outcome
- `volume_fp`, `open_interest_fp` — real liquidity, for a robustness cut
- `open_time` / `close_time`

## Running the pipeline

```
python scripts/fetch_series.py
python scripts/fetch_markets.py --limit-series 800 --seed 42   # bounded pilot
python scripts/fetch_markets.py                                # full ~11k-series crawl (slow, resumable)
python scripts/load_data.py --holdout-months 3
python scripts/calibration_check.py --set discovery
```

`fetch_markets.py` is resumable — a re-run skips series already cached in
`data/raw/markets_by_series/`, so the full crawl can be left running and
picked back up. `load_data.py` splits by `close_time`: everything before
the most recent N months is `discovery.parquet`, the rest is
`holdout.parquet`. **Holdout is not read until a hypothesis is fully
specified on discovery data alone** — same rule as the other two projects,
for the same reason.

## Findings

_To be filled in once the pilot fetch has run — see commit history for
whether this section is still a placeholder or has real numbers in it.
The scaffold and one bounded pilot pull were built and run in the same
session; check the first `calibration_check.py` output for the actual
result before trusting any summary here._

## Rules this project follows

1. Nothing gets called a "signal" until it survives a holdout check that
   happened *after* the method was fully frozen.
2. Every backtest reports returns net of a realistic cost — Kalshi's
   published trading-fee formula here, not just the gross price gap.
3. A result needs a plausible mechanism, not just "the backtest liked it."
4. A finding from another market (Polymarket's documented bias) is a
   hypothesis to test here, not an assumption to import.
5. If nothing survives, that's a reportable result, not a dead end
   reported as one — `strategy-has-no-edge` (crypto) and the closed
   horse-racing project are both acceptable outcomes; so is this one.

## Layout

```
scripts/
  fetch_series.py       # pull Kalshi's full series catalogue
  fetch_markets.py      # pull settled markets per series (resumable, rate-limited)
  load_data.py          # combine + discovery/holdout split -> parquet
  calibration_check.py  # does last price predict actual outcome? (+ category breakdown)
data/
  raw/                  # gitignored — re-fetch with fetch_series.py + fetch_markets.py
  processed/            # gitignored — rebuild with load_data.py
```
