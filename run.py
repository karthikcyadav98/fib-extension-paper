#!/usr/bin/env python3
"""Trend-Based Fibonacci Extension -- CLI.

  python3 run.py backtest    # historical test, fib exits vs a fixed-2R baseline
  python3 run.py update      # advance the live $1000 paper account one step
  python3 run.py signals     # scan for setups on the most recent bars
  python3 run.py serve       # dashboard at http://127.0.0.1:8787
  python3 run.py report      # print the live P&L summary
"""

import datetime as dt
import json
import os
import sys

from fibx import backtest, data, paper, strategy, universe

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(ROOT, "state")


def _ts(ms):
    return dt.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def _write(name, obj):
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, name), "w") as f:
        json.dump(obj, f, indent=2)


def cmd_backtest():
    cfg = strategy.config()
    per_symbol, all_trades = [], {"fib": [], "r2": []}
    print("\n  fetching + testing", len(universe.UNIVERSE), "instruments\n")

    for inst in universe.UNIVERSE:
        try:
            bars = data.fetch_history(inst)
        except Exception as e:
            print(f"  ! {inst['id']:<10} {e}")
            continue
        if len(bars) < 300:
            print(f"  ! {inst['id']:<10} only {len(bars)} bars, skipped")
            continue

        sigs = strategy.scan(bars, cfg)
        row = {"id": inst["id"], "market": inst["market"], "interval": inst["interval"],
               "bars": len(bars), "signals": len(sigs),
               "from": _ts(bars[0]["ts"]), "to": _ts(bars[-1]["ts"])}
        for mode in ("fib", "r2"):
            tr = backtest.simulate_symbol(bars, sigs, cfg, inst["cost_bps"], mode)
            for t in tr:
                t["symbol"] = inst["id"]
                t["market"] = inst["market"]
            all_trades[mode].extend(tr)
            s = backtest.stats(tr)
            s.pop("curve", None)
            row[mode] = s
        per_symbol.append(row)
        print(f"  {inst['id']:<10} {inst['market']:<7} {len(bars):>5} bars  "
              f"{len(sigs):>3} signals  fib {row['fib']['trades']:>3}tr "
              f"{row['fib']['win_rate']:>5.1f}%  {row['fib']['total_R']:+7.2f}R")

    results = {"generated": _ts(__import__("time").time() * 1000), "per_symbol": per_symbol, "markets": {}, "overall": {}}

    for mode in ("fib", "r2"):
        st = backtest.stats(all_trades[mode], 1000.0, 0.01)
        results["overall"][mode] = st
    for mkt in universe.MARKETS:
        results["markets"][mkt] = {}
        for mode in ("fib", "r2"):
            tr = [t for t in all_trades[mode] if t["market"] == mkt]
            s = backtest.stats(tr, 1000.0, 0.01)
            s.pop("curve", None)
            results["markets"][mkt][mode] = s

    results["trades"] = sorted(all_trades["fib"], key=lambda t: t["entry_ts"])[-400:]
    _write("backtest.json", results)

    print("\n  " + "=" * 74)
    print(f"  {'':<10}{'trades':>8}{'win%':>8}{'avgR':>8}{'totalR':>9}{'PF':>7}{'ret%':>9}{'maxDD%':>9}")
    print("  " + "-" * 74)
    for mkt in universe.MARKETS + ["ALL"]:
        for mode in ("fib", "r2"):
            s = results["overall"][mode] if mkt == "ALL" else results["markets"][mkt][mode]
            label = f"{mkt}/{mode}"
            pf = s["profit_factor"]
            print(f"  {label:<10}{s['trades']:>8}{s['win_rate']:>8.1f}{s['avg_R']:>8.2f}"
                  f"{s['total_R']:>9.2f}{(999 if pf == float('inf') else pf):>7.2f}"
                  f"{s['return_pct']:>9.1f}{s['max_dd_pct']:>9.1f}")
        print("  " + "-" * 74)
    print("  fib = 1.272/1.618 scale-out   r2 = same entries, flat 2R target (the null test)")
    print("  " + "=" * 74 + "\n")


def cmd_signals():
    cfg = strategy.config()
    out = []
    for inst in universe.UNIVERSE:
        try:
            bars = data.fetch(inst, ttl=120)
        except Exception as e:
            print(f"  ! {inst['id']}: {e}")
            continue
        if len(bars) < 300:
            continue
        lookback = 30
        sigs = strategy.scan(bars, cfg, first_idx=max(0, len(bars) - lookback))
        for s in sigs:
            s["symbol"] = inst["id"]
            s["market"] = inst["market"]
            s["interval"] = inst["interval"]
            s["bars_ago"] = len(bars) - 1 - s["idx"]
            s.pop("idx", None)
            out.append(s)
    out.sort(key=lambda s: s["ts"], reverse=True)
    _write("signals.json", {"generated": _ts(__import__("time").time() * 1000), "lookback_bars": 30, "signals": out})
    if not out:
        print("\n  no setups triggered in the last 30 bars on any instrument\n")
        return
    print(f"\n  {len(out)} setup(s) in the last 30 bars\n")
    for s in out:
        print(f"  {_ts(s['ts'])}  {s['symbol']:<10}{s['side']:<6}"
              f"entry {s['entry']:<12.6g} stop {s['stop']:<12.6g} "
              f"T1 {s['t1']:<12.6g} T2 {s['t2']:<12.6g} RR {s['rr_t1']:.2f}  ({s['bars_ago']} bars ago)")
    print()


def cmd_update():
    print("\n  updating paper account...")
    state = paper.update(verbose=True)
    paper.save(state)
    cmd_signals()
    cmd_charts()


def cmd_charts():
    """OHLC + live fib geometry for the dashboard's candlestick view."""
    charts = paper.build_charts()
    _write("charts.json", charts)
    live = [k for k, v in charts["pairs"].items() if v["setup"]]
    print(f"  charts: {len(charts['pairs'])} pairs, {len(live)} with a live fib setup")


def cmd_report():
    st = paper.load()
    if not st.get("last_update"):
        print("\n  no live state yet -- run: python3 run.py update\n")
        return
    days = (st["last_update"] - st["started_at"]) / 86400000.0
    eq = st["equity_mtm"]
    pnl = eq - st["start_equity"]
    closed = st["closed"]
    wins = [c for c in closed if c["realised"] > 0]
    print(f"\n  LIVE PAPER ACCOUNT  (started {_ts(st['started_at'])}, {days:.2f} days ago)")
    print("  " + "-" * 56)
    print(f"  start equity      ${st['start_equity']:.2f}")
    print(f"  realised P&L      ${st['realised_pnl']:+.2f}")
    print(f"  unrealised P&L    ${st.get('unrealised_pnl', 0):+.2f}")
    print(f"  equity (MTM)      ${eq:.2f}   ({100 * pnl / st['start_equity']:+.2f}%)")
    print(f"  open positions    {len(st['positions'])}")
    print(f"  closed trades     {len(closed)}"
          + (f"   win rate {100 * len(wins) / len(closed):.1f}%" if closed else ""))
    print("  " + "-" * 56)
    for p in st["positions"]:
        u = ((p["last_price"] - p["entry"]) if p["side"] == "long" else (p["entry"] - p["last_price"])) * p["qty_open"]
        print(f"  OPEN  {p['symbol']:<10}{p['side']:<6} entry {p['entry']:<12.6g} "
              f"now {p['last_price']:<12.6g} unrl ${u:+.2f}")
    for c in closed[-10:]:
        print(f"  DONE  {c['symbol']:<10}{c['side']:<6} {c['exit_reason']:<10} "
              f"R {c['R']:+.2f}  ${c['realised']:+.2f}")
    print()


def cmd_serve():
    from fibx import server
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8787
    server.serve(port)


def cmd_robust():
    from fibx import robustness
    print("\n  parameter sweep -- 72 configurations x 13 instruments\n")
    rows = robustness.sweep()
    summ = robustness.summarise(rows)
    _write("robustness.json", {"summary": {k: v for k, v in summ.items() if k not in ("best", "worst")},
                               "best": summ["best"], "worst": summ["worst"], "rows": rows})

    print("\n  " + "=" * 70)
    print(f"  cells tested            {summ['cells']}")
    print(f"  profitable (avgR > 0)   {summ['profitable_cells']} / {summ['cells']}")
    print(f"  fib beat the 2R null    {summ['fib_beats_r2_cells']} / {summ['cells']}")
    print(f"  win rate    median {summ['median_win_rate']:.1f}%   "
          f"range {summ['win_rate_range'][0]:.1f}% - {summ['win_rate_range'][1]:.1f}%")
    print(f"  avg R       median {summ['median_avg_R']:+.3f}    "
          f"range {summ['avg_R_range'][0]:+.3f} - {summ['avg_R_range'][1]:+.3f}")
    print("  " + "-" * 70)
    print(f"  {'market':<10}{'cells':>7}{'profitable':>12}{'med win%':>10}{'med avgR':>10}{'best avgR':>11}")
    for mkt, m in summ["by_market"].items():
        print(f"  {mkt:<10}{m['cells']:>7}{m['profitable_cells']:>12}{m['median_win_rate']:>10.1f}"
              f"{m['median_avg_R']:>+10.3f}{m['best_avg_R']:>+11.3f}")
    print("  " + "-" * 70)
    b = summ["best"]
    print(f"  best cell   {b['params']}")
    print(f"              {b['fib']['trades']}tr  win {b['fib']['win_rate']:.1f}%  "
          f"avgR {b['fib']['avg_R']:+.3f}  PF {b['fib']['profit_factor']:.2f}")
    print("  " + "=" * 70 + "\n")


CMDS = {"backtest": cmd_backtest, "update": cmd_update, "signals": cmd_signals,
        "report": cmd_report, "serve": cmd_serve, "robust": cmd_robust,
        "charts": cmd_charts}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd not in CMDS:
        print(__doc__)
        sys.exit(1)
    CMDS[cmd]()
