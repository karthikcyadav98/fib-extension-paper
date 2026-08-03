# Trend-Based Fibonacci Extension — live forex paper trading

A mechanised implementation of the "trend-based fib extension" strategy, now
running **forex-only across 16 pairs on 4h bars**, with free keyless data, a
historical test, an out-of-sample research harness, a live $1,000 paper account
and a web dashboard. Hosted on GitHub Actions; the dashboard is on Pages.

**Headline result: it does not have an edge.** On 16 pairs it measures
-0.07R per trade at a 33.8% win rate (PF 0.88). Every time the sample was
widened, the apparent edge shrank — see *Findings*.

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

**16 forex pairs on 4h bars**, resampled from Yahoo's 1h feed (Yahoo has no
native 4h): 7 majors (EURUSD GBPUSD USDJPY AUDUSD USDCHF USDCAD NZDUSD) and
9 crosses (EURGBP EURJPY EURCHF EURAUD AUDJPY CADJPY GBPJPY CHFJPY GBPAUD).
Crypto and India remain in `universe.REFERENCE` for comparison only.

Three gotchas, all handled in `fibx/data.py`:
Yahoo **429s a full Chrome user-agent** but serves a short one; python.org
Python ships **no CA bundle** (falls back to certifi or the macOS bundle); and
resampling **buckets by absolute time, not by counting bars** — counting would
fuse Friday and Sunday bars across the weekend close into one bar whose
high/low range never traded.

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

**3. Widening the sample destroys every apparent edge.** This happened three
times, in the same direction each time:

| Sample | Trades | Avg R |
|---|---|---|
| crypto, 4 pairs | 152 | **+0.18** |
| crypto, 10 pairs | 384 | **+0.01** |
| forex 4h, 4 pairs | 97 | **+0.006** |
| forex 4h, 16 pairs | 355 | **−0.07** |

A strategy with a real edge does not behave this way. This is what a
zero-edge process looks like when you keep drawing from it.

**3b. Out-of-sample variant testing found nothing.** `research.py` evaluates 12
hypothesis-driven variants (regime filters, retracement caps, exit models, R:R
floors) on a 70/30 time split. **None cleared 2 standard errors out of sample.**
The train winner (+0.559R) collapsed to +0.180 ±0.393 on 21 test trades. The
best-looking filter turned out to be nothing but "don't trade 1h forex".
A session-of-day effect (Asia +0.147R) decayed from +0.264R to +0.029R across
a split-half test — noise, not signal.

**4. The live config is optimistic by construction.** `strategy.DEFAULTS` is the
best cell of the sweep — chosen *after* seeing results. Live performance should
be expected to fall short of the backtest, not match it.

## Data latency — read this before calling it "live"

Bars come from Yahoo's 1h feed, resampled to 4h, and the runner fires hourly.
**A just-closed bar is therefore up to ~55 minutes old**, and a 4h bar only
finalises every 4 hours. That is fine for a 4h strategy — no signal is missed,
because `update` replays every bar since the last run — but it is *hourly batch*,
not streaming, and the dashboard timestamp reflects that.

For true streaming prices and real demo-account order execution, the system
needs an **OANDA practice API token** (free). See `LIVE.md`.

## Live paper account

`run.py update` is idempotent per bar: every symbol stores the timestamp of the
last bar it processed, so running it twice in a minute cannot double-trade. The
first run adopts history without back-filling imaginary trades, so the test
starts genuinely flat. $1,000 start, 1% equity risked per trade, max 8 concurrent
positions, 35% notional cap per position.

**Currency exposure cap.** 16 FX pairs are not 16 independent bets: six
USD-quoted longs are one leveraged USD short. `paper.py` tracks net directional
exposure per currency and refuses any entry that would push a single currency
past `MAX_CCY_EXPOSURE` (3). This is the risk control an FX book actually needs;
position count alone does not provide it.

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
fibx/diagnose.py     trade decomposition by side/exit/regime/volatility
fibx/research.py     out-of-sample variant testing on a 70/30 time split
fibx/paper.py        live $1,000 paper broker
fibx/server.py       stdlib dashboard server
web/index.html       dashboard
state/               portfolio.json, backtest.json, signals.json, robustness.json
```

## Caveat

Simulated results on historical data. Not investment advice. The point of this
repo is that it reports what the strategy actually did, including when that is
unflattering.
