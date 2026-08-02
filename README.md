# Trend-Based Fibonacci Extension — mechanised, backtested, paper-traded

A full implementation of the "trend-based fib extension" strategy across three
markets (Indian equities, forex, crypto), with free keyless data, a historical
test, a parameter sweep, a live $1,000 paper account and a web dashboard.

**Headline result: it does not have an edge.** Details in *Findings* below.

## Quick start

No dependencies, no API keys, no virtualenv — Python 3 stdlib only.

```bash
python3 run.py backtest   # historical test, fib exits vs a flat-2R null model
python3 run.py robust     # 72-configuration parameter sweep
python3 run.py update     # advance the live paper account one step
python3 run.py signals    # setups on the last 30 bars
python3 run.py report     # live P&L summary
python3 run.py serve      # dashboard on http://127.0.0.1:8787
./install_cron.sh         # run `update` hourly so the 7-day test advances
```

## The rules

The discretionary version of this strategy is untestable, because every trader
picks different swing points and therefore gets different levels. The whole
implementation rests on making the anchor selection mechanical:

| | |
|---|---|
| **P1** | confirmed swing low — impulse origin |
| **P2** | confirmed swing high after P1 — impulse peak |
| **P3** | confirmed swing low after P2, above P1 — pullback trough |
| leg | `P2 − P1` |
| retracement | `(P2 − P3) / leg`, must land in 23.6%–78.6% |
| **T1** | `P3 + 1.272 × leg` — exit half |
| **T2** | `P3 + 1.618 × leg` — exit the rest |
| stop | `P3 − 1.5 × ATR(14)`, to breakeven after T1 |
| trend filter | `close > EMA50 > EMA200` (mirrored for shorts) |
| trigger | first close through the prior bar's extreme, within 10 bars of P3 confirming |
| quality | reward:risk to T1 must be ≥ 2.0 |

Pivots need `pivot_right` bars of confirmation, and each is used only from its
`confirm_idx` onward, so no signal can be built from a bar that had not printed.

## Data (free, keyless)

| Market | Source | Timeframe | Why |
|---|---|---|---|
| forex — EURUSD, GBPUSD, USDJPY, AUDUSD | Yahoo chart API | 1h | deepest liquidity, 24/5, cleanest swings |
| crypto — BTC, ETH, SOL, BNB | Binance public REST | 4h | strongest trends, but wicks need a slower TF |
| india — NIFTY, RELIANCE, HDFCBANK, INFY, TCS | Yahoo chart API | 1d | overnight gaps destroy intraday swing structure |

Two gotchas worth knowing, both already handled in `fibx/data.py`:
Yahoo **429s a full Chrome user-agent string** but serves a short one, and
python.org Python ships **no CA bundle**, so the SSL context falls back to
certifi or the macOS system bundle.

## Cost model

`cost_bps` in `universe.py` is one-way and all-in (spread + commission +
slippage), charged on every fill. This is not a detail — a 1h EURUSD stop is
only a few bps wide, and an early over-charge of ~6bps round trip made forex
look far worse than it is. Fills are conservative: a bar containing both stop
and target is scored a **stop**, and gaps fill at the **open**, not the level.

## Findings

**1. Across a 72-cell parameter sweep (1,281 trades), 1 cell was profitable.**
Median cell: 29.3% win rate, −0.12R per trade. Best cell: +0.002R — breakeven to
three decimals. The strategy is not one bad parameter choice away from working;
it is flat-to-negative across the whole surface.

**2. Fibonacci levels are not the edge, but the exit *structure* is worth something.**
The `r2` null model takes identical entries and stops with a flat 2R target. Fib
scale-out beat it in 51 of 72 cells — but that is the *scale-out-and-trail*
mechanic, not the numbers 1.272 and 1.618. Any comparable pair of targets would
likely do the same.

**3. Ranking by market, on the best-of-sweep config:**

| Market | Trades | Win rate | Avg R | PF |
|---|---|---|---|---|
| crypto | 152 | 34.9% | +0.18 | 1.29 |
| forex | 405 | 32.8% | −0.05 | 0.92 |
| india | 29 | 34.5% | −0.20 | 0.65 |

Crypto is the only market that is positive, and it is the one with the smallest
sample. With ~150 trades and a per-trade standard deviation near 1.3R, the
standard error on that +0.18R is about ±0.11R — so it is roughly 1.6 standard
errors from zero. Suggestive, not significant, and selected after the fact.

**4. The live config is optimistic by construction.** `strategy.DEFAULTS` is the
best cell of the sweep — chosen *after* seeing results. Live performance should
be expected to fall short of the backtest, not match it.

## Live paper account

`run.py update` is idempotent per bar: every symbol stores the timestamp of the
last bar it processed, so running it twice in a minute cannot double-trade. The
first run adopts history without back-filling imaginary trades, so the test
starts genuinely flat. $1,000 start, 1% equity risked per trade, max 6 concurrent
positions, 35% notional cap per position.

**On missed runs.** The hourly cron does not fire while the machine is asleep and
macOS never replays skipped jobs, so bars pile up between updates. `update`
therefore replays *every* bar that printed since the last run, in order, opening
and closing positions as it goes — checking only the newest bar (the original
behaviour) silently discarded entry signals from the bars in between. A laptop
sleeping overnight is now harmless: the next run catches up.

## Layout

```
fibx/data.py         keyless fetchers, disk cache, SSL + UA workarounds
fibx/universe.py     instruments, timeframes, per-instrument costs
fibx/indicators.py   EMA, Wilder ATR, fractal pivots
fibx/strategy.py     anchor selection + signal generation
fibx/backtest.py     fill simulation, portfolio compounding, stats
fibx/robustness.py   parameter sweep
fibx/paper.py        live $1,000 paper broker
fibx/server.py       stdlib dashboard server
web/index.html       dashboard
state/               portfolio.json, backtest.json, signals.json, robustness.json
```

## Caveat

Simulated results on historical data. Not investment advice. The point of this
repo is that it reports what the strategy actually did, including when that is
unflattering.
