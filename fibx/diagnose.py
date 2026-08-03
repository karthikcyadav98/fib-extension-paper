"""Where does the money actually go?

Before changing a strategy it is worth knowing which slice of trades is bleeding.
This decomposes the trade population along the dimensions that could plausibly
matter and reports mean R per bucket, so a fix can target a mechanism rather
than being a parameter guess.

Read the `n` column first: a bucket with 15 trades tells you nothing.
"""

from . import backtest, data, strategy, universe


def collect(cfg=None, instruments=None, verbose=True):
    cfg = cfg or strategy.config()
    instruments = instruments or universe.UNIVERSE
    out = []
    for inst in instruments:
        try:
            bars = data.fetch_history(inst)
        except Exception as e:
            if verbose:
                print(f"  ! {inst['id']}: {e}")
            continue
        if len(bars) < 300:
            continue
        sigs = strategy.scan(bars, cfg)
        by_idx = {s["idx"]: s for s in sigs}
        for t in backtest.simulate_symbol(bars, sigs, cfg, inst["cost_bps"], "fib"):
            s = by_idx.get(t["entry_idx"])
            if not s:
                continue
            t.update({
                "symbol": inst["id"], "market": inst["market"],
                "trend_str": s["trend_str"], "atr_pct": s["atr_pct"],
                "entry_ext": s["entry_ext"], "leg_pct": s["leg_pct"],
                "rr_t1": s["rr_t1"],
            })
            out.append(t)
    return out


def _bucket(trades, key, edges, labels):
    groups = {l: [] for l in labels}
    for t in trades:
        v = t[key]
        for i, e in enumerate(edges):
            if v <= e:
                groups[labels[i]].append(t)
                break
        else:
            groups[labels[-1]].append(t)
    return groups


def _line(name, ts):
    if not ts:
        return f"  {name:<22}{0:>6}{'':>10}{'':>10}{'':>10}"
    Rs = [t["R"] for t in ts]
    win = 100 * sum(1 for r in Rs if r > 0) / len(Rs)
    return (f"  {name:<22}{len(ts):>6}{win:>9.1f}%{sum(Rs) / len(Rs):>+10.3f}{sum(Rs):>+10.1f}")


HEAD = f"  {'BUCKET':<22}{'N':>6}{'WIN':>10}{'AVG R':>10}{'TOT R':>10}"


def report(trades):
    print(f"\n  {len(trades)} trades\n")

    def block(title, groups):
        print(f"  --- {title} " + "-" * (52 - len(title)))
        print(HEAD)
        for k, v in groups.items():
            print(_line(str(k), v))
        print()

    block("by side", {s: [t for t in trades if t["side"] == s] for s in ("long", "short")})
    block("by market", {m: [t for t in trades if t["market"] == m] for m in universe.MARKETS})
    block("by exit reason", {r: [t for t in trades if t["reason"] == r]
                             for r in ("stop", "breakeven", "target", "time")})
    block("by retracement depth", _bucket(
        trades, "retrace", [0.382, 0.5, 0.618, 0.786],
        ["shallow <=38.2%", "38.2-50%", "50-61.8%", "61.8-78.6%", "deep >78.6%"]))
    block("by entry lateness (how far past P3 the trigger fired, x leg)", _bucket(
        trades, "entry_ext", [0.25, 0.5, 0.75],
        ["early <=0.25", "0.25-0.50", "0.50-0.75", "late >0.75"]))
    block("by trend strength (EMA50-200 gap / price)", _bucket(
        trades, "trend_str", [0.005, 0.015, 0.03],
        ["flat <=0.5%", "0.5-1.5%", "1.5-3%", "steep >3%"]))
    block("by volatility (ATR / price)", _bucket(
        trades, "atr_pct", [0.005, 0.01, 0.02],
        ["quiet <=0.5%", "0.5-1%", "1-2%", "wild >2%"]))
    block("by planned R:R to T1", _bucket(
        trades, "rr_t1", [2.5, 3.5, 5.0],
        ["2.0-2.5", "2.5-3.5", "3.5-5.0", ">5.0"]))
