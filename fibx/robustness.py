"""Parameter sweep.

A single backtest tells you almost nothing -- any set of parameters can be lucky
or unlucky. This sweeps the four parameters a discretionary trader would argue
about and reports the whole surface, so the conclusion rests on "what happens
across the parameter space" rather than "what happened at my favourite setting".

For every cell it also runs the fixed-2R null model on identical entries, which
is what isolates whether the Fibonacci LEVELS contribute anything.
"""

import itertools

from . import backtest, data, strategy, universe

GRID = {
    "stop_atr_mult": [0.25, 0.5, 1.0, 1.5],
    "min_rr": [1.0, 1.5, 2.0],
    "pivot_left": [2, 3, 5],
    "entry_window": [5, 10],
}


def sweep(instruments=None, verbose=True):
    instruments = instruments or universe.UNIVERSE
    loaded = []
    for inst in instruments:
        try:
            loaded.append((inst, data.fetch_history(inst)))
        except Exception as e:
            if verbose:
                print(f"  ! {inst['id']}: {e}")
    if verbose:
        print(f"  loaded {len(loaded)} instruments")

    keys = list(GRID)
    combos = list(itertools.product(*(GRID[k] for k in keys)))
    rows = []

    for n, combo in enumerate(combos, 1):
        params = dict(zip(keys, combo))
        cfg = strategy.config(pivot_right=params["pivot_left"], **params)
        trades = {"fib": [], "r2": []}
        for inst, bars in loaded:
            sigs = strategy.scan(bars, cfg)
            for mode in ("fib", "r2"):
                tr = backtest.simulate_symbol(bars, sigs, cfg, inst["cost_bps"], mode)
                for t in tr:
                    t["market"] = inst["market"]
                trades[mode].extend(tr)

        row = {"params": params}
        for mode in ("fib", "r2"):
            s = backtest.stats(trades[mode])
            s.pop("curve", None)
            row[mode] = s
        row["markets"] = {}
        for mkt in universe.MARKETS:
            s = backtest.stats([t for t in trades["fib"] if t["market"] == mkt])
            s.pop("curve", None)
            row["markets"][mkt] = s
        rows.append(row)
        if verbose:
            f = row["fib"]
            print(f"  [{n:>3}/{len(combos)}] stop{params['stop_atr_mult']:<5} rr{params['min_rr']:<4} "
                  f"piv{params['pivot_left']:<3} win{params['entry_window']:<3} -> "
                  f"{f['trades']:>5}tr {f['win_rate']:>5.1f}%  {f['avg_R']:+.3f}R  PF {f['profit_factor']:.2f}")
    return rows


def summarise(rows):
    prof = [r for r in rows if r["fib"]["avg_R"] > 0]
    fib_beats = [r for r in rows if r["fib"]["total_R"] > r["r2"]["total_R"]]
    by_market = {}
    for mkt in universe.MARKETS:
        cells = [r["markets"][mkt] for r in rows if r["markets"][mkt]["trades"] >= 30]
        if cells:
            by_market[mkt] = {
                "cells": len(cells),
                "profitable_cells": sum(1 for c in cells if c["avg_R"] > 0),
                "median_win_rate": sorted(c["win_rate"] for c in cells)[len(cells) // 2],
                "median_avg_R": sorted(c["avg_R"] for c in cells)[len(cells) // 2],
                "best_avg_R": max(c["avg_R"] for c in cells),
                "worst_avg_R": min(c["avg_R"] for c in cells),
            }
    ws = sorted(r["fib"]["win_rate"] for r in rows)
    ars = sorted(r["fib"]["avg_R"] for r in rows)
    return {
        "cells": len(rows),
        "profitable_cells": len(prof),
        "fib_beats_r2_cells": len(fib_beats),
        "median_win_rate": ws[len(ws) // 2],
        "win_rate_range": [ws[0], ws[-1]],
        "median_avg_R": ars[len(ars) // 2],
        "avg_R_range": [ars[0], ars[-1]],
        "best": max(rows, key=lambda r: r["fib"]["avg_R"]),
        "worst": min(rows, key=lambda r: r["fib"]["avg_R"]),
        "by_market": by_market,
    }
