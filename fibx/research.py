"""Out-of-sample evaluation of strategy variants.

The diagnostics in diagnose.py were computed on the whole history, so anything
chosen from them is contaminated by hindsight. This module keeps the two jobs
apart:

  TRAIN  the older 70% of every instrument's bars -- variants are chosen here
  TEST   the newest 30% -- never consulted while choosing, reported once

Indicators still warm up across the whole series (an EMA200 needs history), but
a signal is assigned to TEST only if its entry bar falls after the split, so no
trade is selected using data from its own future.

The variants are hypotheses drawn from the trade decomposition, not a parameter
grid: each one names a mechanism that could explain the losses. Even so, trying
N of them and keeping the winner inflates the winner -- so the summary reports
how the *whole set* did out of sample, not just the champion.
"""

import math

from . import backtest, data, strategy, universe

SPLIT = 0.70

# Each entry: (name, hypothesis, config overrides)
VARIANTS = [
    ("baseline", "current live settings", {}),
    ("vol-filter", "skip dead markets: ATR must be >= 0.5% of price", {"min_atr_pct": 0.005}),
    ("trend-filter", "skip flat regimes: EMA50-200 gap >= 0.5% of price", {"min_trend_str": 0.005}),
    ("shallow-only", "deep retracements lose; cap at 50%", {"retrace_max": 0.50}),
    ("single-target", "T2 almost never hits; take it all at T1", {"single_target": True}),
    ("fast-exit", "the time stop is the real exit; shorten it", {"max_bars_in_trade": 30}),
    ("slow-exit", "or give the runner more room", {"max_bars_in_trade": 120}),
    ("high-rr", "only take setups paying >= 3.5R", {"min_rr": 3.5}),
    ("regime", "vol + trend filters together", {"min_atr_pct": 0.005, "min_trend_str": 0.005}),
    ("regime+shallow", "regime filters plus the retracement cap",
     {"min_atr_pct": 0.005, "min_trend_str": 0.005, "retrace_max": 0.50}),
    ("regime+single", "regime filters, all out at T1",
     {"min_atr_pct": 0.005, "min_trend_str": 0.005, "single_target": True}),
    ("kitchen-sink", "every filter that helped, together",
     {"min_atr_pct": 0.005, "min_trend_str": 0.005, "retrace_max": 0.50,
      "single_target": True, "min_rr": 3.5}),
]


def load_all(verbose=True):
    out = []
    for inst in universe.UNIVERSE:
        try:
            bars = data.fetch(inst, ttl=999999)
        except Exception as e:
            if verbose:
                print(f"  ! {inst['id']}: {e}")
            continue
        if len(bars) >= 400:
            out.append((inst, bars, int(len(bars) * SPLIT)))
    return out


def evaluate(loaded, overrides):
    """Return (train_stats, test_stats) for one variant."""
    cfg = strategy.config(**overrides)
    trades = {"train": [], "test": []}
    for inst, bars, cut in loaded:
        sigs = strategy.scan(bars, cfg)
        for split, subset in (("train", [s for s in sigs if s["idx"] < cut]),
                              ("test", [s for s in sigs if s["idx"] >= cut])):
            tr = backtest.simulate_symbol(bars, subset, cfg, inst["cost_bps"], "fib")
            for t in tr:
                t["market"] = inst["market"]
            trades[split].extend(tr)
    return (backtest.stats(trades["train"]), backtest.stats(trades["test"]), trades)


def stderr_R(trades):
    """Standard error of mean R -- the honest error bar on 'avg R'."""
    if len(trades) < 2:
        return float("inf")
    Rs = [t["R"] for t in trades]
    m = sum(Rs) / len(Rs)
    var = sum((r - m) ** 2 for r in Rs) / (len(Rs) - 1)
    return math.sqrt(var / len(Rs))


def run(verbose=True):
    loaded = load_all(verbose)
    if verbose:
        print(f"  {len(loaded)} instruments | train = oldest {SPLIT:.0%} of bars, test = newest {1 - SPLIT:.0%}\n")
        print(f"  {'VARIANT':<16}{'TRAIN n':>9}{'avgR':>9}{'TEST n':>9}{'avgR':>9}{'±SE':>8}{'win%':>8}{'PF':>7}")
        print("  " + "-" * 75)

    rows = []
    for name, hypothesis, ov in VARIANTS:
        tr_s, te_s, trades = evaluate(loaded, ov)
        se = stderr_R(trades["test"])
        row = {"name": name, "hypothesis": hypothesis, "overrides": ov,
               "train": {k: v for k, v in tr_s.items() if k != "curve"},
               "test": {k: v for k, v in te_s.items() if k != "curve"},
               "test_se": se}
        rows.append(row)
        if verbose:
            pf = te_s["profit_factor"]
            print(f"  {name:<16}{tr_s['trades']:>9}{tr_s['avg_R']:>+9.3f}"
                  f"{te_s['trades']:>9}{te_s['avg_R']:>+9.3f}{se:>8.3f}"
                  f"{te_s['win_rate']:>8.1f}{(99 if pf == float('inf') else pf):>7.2f}")
    return rows
