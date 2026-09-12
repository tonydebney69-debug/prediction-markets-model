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

**Pilot run: 800 series sampled (of ~12,475 target-category series), ~43,000
settled markets fetched, 30,129 usable after cleaning. Discovery = Jul–Aug
2026 (32,566 rows); holdout = Sep 2026 (10,471 rows, untouched).**

### 1. "Last traded price" is the wrong pre-resolution snapshot for most of this data

Before any calibration question, the price data itself needed a sanity
check — and it failed one. **94% of settled markets have a last traded
price at or below 2¢ or at or above 98¢.** Only 6% (1,855 of 30,129) settled
with a last price anywhere in a genuinely uncertain 2¢–98¢ range.

The reason: unlike Betfair's BSP (fixed at a specific meaningful moment —
the race off), Kalshi's `last_price_dollars` is just whatever the final
trade happened to be, whenever it happened, including trades placed
*after* the outcome was already effectively known (a game just ended, the
temperature was already recorded). For most of this sample — mostly
short-duration, high-frequency sports and weather markets — trading
continues right up to that moment, so the "last price" mostly measures
"did the market notice the outcome," not "did the market forecast it."
This is a close cousin of the racing.com pilot's circularity problem: a
measurement that's contaminated by information from after the moment it's
supposed to be predicting.

**Fix for next time:** use price at a fixed horizon before resolution
(e.g. 24 hours out, or at market open) via Kalshi's candlestick/price-
history endpoint, not the settled-market summary's last trade. Not yet
built — the current fetch only pulls the settlement summary.

### 2. The Sports gap — partly fixed by event normalisation, partly a new open question (`scripts/event_field_normalization.py`)

The pilot found "yes" looking heavily overpriced in the middle of the
price range, concentrated in Sports (61% of the genuinely-uncertain
subset). The suspected cause: many Sports markets are one-of-many
contracts over an exhaustive field ("will William Byron have the fastest
lap?" is one of ~20-40 near-identical per-driver markets for a race with
exactly one winner) pooled without grouping by event first — the same
problem horse racing solved by normalising each runner's price against
its own race's overround.

**Confirmed and fixed.** Classified every Sports series empirically:
group its markets by event, and check how many resolve "yes" per event
across all its events. A series where that's consistently exactly 1 is
an exhaustive field (fastest-lap, match-winner, 3-way, exact-score); a
series where it's often 0, 2, 3+ is something else (nested over/under
ladders, independent props) and was left untouched. **22 of 49
classifiable Sports series (4,300 of 27,330 Sports rows) were exhaustive
fields**, each renormalised the way a horse race is: divide each
contract's price by the sum of all its field's prices.

The fix visibly worked. Restricting to the exhaustive-field-normalised
markets plus genuine standalone singles (the "clean" subset, n=15,211):

| Bucket (normalised price) | n | Implied | Actual | Edge |
|---|---|---|---|---|
| 2.9% | 133 | 2.9% | 0.0% | -2.9 |
| 4.8% | 133 | 4.8% | 0.0% | -4.8 |
| 11.4% | 134 | 11.4% | 1.5% | -9.9 |
| 38.8% | 132 | 38.8% | 39.4% | **+0.6** |
| 88.2% | 203 | 88.2% | 98.0% | +9.8 |
| 96.7% | 63 | 96.7% | 96.8% | **+0.1** |

Compare to the pre-fix middle and top buckets, which ran -24 to -33
points — the normalisation removed most of the apparent bias. What's
left in the low buckets (n≈133 each) is small enough to plausibly be
noise, not confirmed either way.

**But it isn't the whole story.** The markets left alone — nested
over/under and spread ladders (total runs, game spreads: `KXMLBF5TOTAL`,
`KXWNBA2QSPREAD`, `KXUELTEAMTOTAL` and similar) — still show large gaps
after the fix, because the fix was never meant to touch them:

| Bucket | n | Implied | Actual | Edge |
|---|---|---|---|---|
| 20.9% | 75 | 20.9% | 1.3% | -19.6 |
| 43.1% | 78 | 43.1% | 1.3% | -41.8 |
| 75.2% | 81 | 75.2% | 39.5% | -35.7 |

These are a genuinely different structure (several thresholds under one
game can resolve yes simultaneously — "over 3.5 runs" and "over 4.5 runs"
aren't mutually exclusive the way fastest-lap entrants are), so forcing
them into the same field-sum normalisation would be wrong in the other
direction. **This is now an open question, not a fix** — something about
how these nested-ladder markets settle looks substantially miscalibrated,
and the mechanism isn't understood yet. Flagged for follow-up, not
reported as a result: n is small (75-90 per bucket) and no hypothesis for
*why* has been tested.

The non-Sports categories in the original uncertain-price subset don't
have either structural problem (each is a standalone yes/no proposition),
but they're too small to read anything into yet:

| Category | n | Implied yes | Actual yes |
|---|---|---|---|
| Climate and Weather | 460 | 72.7% | 73.3% |
| Politics | 73 | 33.7% | 34.2% |
| Economics | 81 | 40.5% | 23.5% |
| Entertainment | 40 | 34.1% | 22.5% |
| Mentions | 30 | 34.1% | 26.7% |

Climate and Politics — the two with more than a handful of markets — are
tightly calibrated. Economics and Entertainment show gaps, but on 40-80
markets a handful of surprises swings the percentage by 10+ points; not
distinguishable from noise yet.

### Verdict on this pilot: inconclusive, and the real output is the methodology fix list

No result here clears the bar this project (and its two predecessors)
sets for a finding. That's not a failure of the pilot — it's exactly what
a pilot is for. Status on what it needs before it can produce a
trustworthy answer to "is Kalshi as efficient as Betfair":

1. ~~Event-grouped normalisation for exhaustive multi-entrant markets~~ —
   **done** (`event_field_normalization.py`). Fixed most of the Sports gap;
   also surfaced a second, different, still-unexplained gap in nested
   over/under and spread markets — see finding #2.
2. **A real pre-resolution price snapshot** (fixed horizon via candlesticks,
   not last-trade) instead of the near-tautological one used here — still
   open, and now the higher-priority fix given #1 turned out to be only
   part of the Sports picture.
3. **Understand the nested-ladder gap** (over/under, spreads) before
   dismissing or trusting it — needs a mechanism hypothesis, not just a
   number, per this project's own rules.
4. **More data** — 800 of ~12,475 series, concentrated in 2 months because
   that's what a random sample of mostly-recent series happened to
   produce. The full crawl (`fetch_markets.py` with no `--limit-series`)
   reaches much further back and would give real category-level sample
   sizes, especially for Politics and Elections.

Not run against holdout — nothing here is close to a frozen, testable
method yet.

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
  load_data.py                   # combine + discovery/holdout split -> parquet
  calibration_check.py           # does last price predict actual outcome? (+ category breakdown)
  event_field_normalization.py   # fixes the exhaustive-field Sports bug from finding #2
data/
  raw/                  # gitignored — re-fetch with fetch_series.py + fetch_markets.py
  processed/            # gitignored — rebuild with load_data.py
```
