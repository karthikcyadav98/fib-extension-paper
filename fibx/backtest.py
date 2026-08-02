"""Bar-by-bar trade simulation + portfolio aggregation.

Two exit models are simulated from the SAME entries and stops:

  fib   scale 50% at the 1.272 extension, stop to breakeven, rest at 1.618
  r2    single exit at a fixed 2R target

`r2` is the null hypothesis. If `fib` does not beat it, the Fibonacci levels
are not the edge -- the trend filter and the risk-to-reward are. That comparison
is the whole point of running this, so it is reported everywhere the fib numbers
are reported.

Conservative fill assumptions:
  * entry at the signal bar's close, plus fee and slippage
  * if a bar's range contains both the stop and a target, the STOP is taken
  * gaps fill at the open, not the level (matters for Indian daily bars)
"""

def _fill(price, side, direction, cost_bps):
    """Apply all-in cost (spread + commission + slippage) against us.

    cost_bps is ONE-WAY and already includes slippage, so a round trip pays it
    twice. Values live in universe.py and are set per instrument -- a 1h EURUSD
    stop is only a few bps wide, so getting this wrong decides the whole result.
    """
    cost = cost_bps / 10000.0
    adverse = 1 if (side == "long") == (direction == "in") else -1
    return price * (1 + adverse * cost)


def simulate_symbol(bars, signals, cfg, cost_bps, mode="fib"):
    """Walk each signal forward through the bars and close it. Returns trades."""
    trades = []
    busy_until = -1  # one position per symbol at a time

    for sig in signals:
        i = sig["idx"]
        if i <= busy_until:
            continue

        side = sig["side"]
        entry = _fill(sig["entry"], side, "in", cost_bps)
        stop = sig["stop"]
        risk = abs(entry - stop)
        if risk <= 0:
            continue

        if mode == "r2":
            targets = [(entry + 2 * risk if side == "long" else entry - 2 * risk, 1.0)]
        else:
            targets = [(sig["t1"], 0.5), (sig["t2"], 0.5)]

        remaining = 1.0
        realised = 0.0          # in R
        legs = []
        cur_stop = stop
        ti = 0
        exit_idx = None
        exit_reason = None

        for j in range(i + 1, min(len(bars), i + cfg["max_bars_in_trade"] + 1)):
            bar = bars[j]
            hit_stop = bar["low"] <= cur_stop if side == "long" else bar["high"] >= cur_stop
            tgt = targets[ti][0] if ti < len(targets) else None
            hit_tgt = tgt is not None and (bar["high"] >= tgt if side == "long" else bar["low"] <= tgt)

            if hit_stop:
                # Gap through the stop fills at the open, not at the level.
                px = bar["open"] if ((side == "long" and bar["open"] < cur_stop) or (side == "short" and bar["open"] > cur_stop)) else cur_stop
                px = _fill(px, side, "out", cost_bps)
                pnl = (px - entry) if side == "long" else (entry - px)
                realised += remaining * pnl / risk
                legs.append({"kind": "stop", "idx": j, "price": px, "frac": remaining})
                remaining = 0.0
                exit_idx, exit_reason = j, ("stop" if cur_stop == stop else "breakeven")
                break

            if hit_tgt:
                frac = targets[ti][1]
                px = _fill(tgt, side, "out", cost_bps)
                pnl = (px - entry) if side == "long" else (entry - px)
                realised += frac * pnl / risk
                legs.append({"kind": f"t{ti + 1}", "idx": j, "price": px, "frac": frac})
                remaining -= frac
                ti += 1
                if mode == "fib" and ti == 1:
                    cur_stop = entry  # breakeven after the first scale-out
                if remaining <= 1e-9:
                    exit_idx, exit_reason = j, "target"
                    break

        if remaining > 1e-9:
            j = min(len(bars) - 1, i + cfg["max_bars_in_trade"])
            if j > i:
                px = _fill(bars[j]["close"], side, "out", cost_bps)
                pnl = (px - entry) if side == "long" else (entry - px)
                realised += remaining * pnl / risk
                legs.append({"kind": "time", "idx": j, "price": px, "frac": remaining})
                exit_idx, exit_reason = j, "time"
            else:
                continue  # still open at the end of history -- not a closed trade

        busy_until = exit_idx
        trades.append(
            {
                "side": side,
                "entry_idx": i,
                "entry_ts": bars[i]["ts"],
                "exit_idx": exit_idx,
                "exit_ts": bars[exit_idx]["ts"],
                "entry": entry,
                "stop": stop,
                "t1": sig["t1"],
                "t2": sig["t2"],
                "R": realised,
                "reason": exit_reason,
                "bars_held": exit_idx - i,
                "retrace": sig["retrace"],
                "legs": legs,
            }
        )
    return trades


def portfolio(trades, start_equity=1000.0, risk_pct=0.01):
    """Event-driven compounding: risk `risk_pct` of equity as it stands at entry."""
    events = []
    for t in trades:
        events.append((t["entry_ts"], 0, t))   # 0 sorts entries before exits
        events.append((t["exit_ts"], 1, t))
    events.sort(key=lambda e: (e[0], e[1]))

    equity = start_equity
    staked = {}
    curve = [{"ts": events[0][0] if events else 0, "equity": equity}]
    for ts, kind, t in events:
        tid = id(t)
        if kind == 0:
            staked[tid] = equity * risk_pct
        else:
            pnl = staked.pop(tid, equity * risk_pct) * t["R"]
            equity += pnl
            t["pnl"] = pnl
            curve.append({"ts": ts, "equity": equity})
    return equity, curve


def stats(trades, start_equity=1000.0, risk_pct=0.01):
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "avg_R": 0.0, "expectancy_R": 0.0,
                "total_R": 0.0, "profit_factor": 0.0, "max_dd_pct": 0.0,
                "final_equity": start_equity, "return_pct": 0.0, "curve": []}

    equity, curve = portfolio(trades, start_equity, risk_pct)
    Rs = [t["R"] for t in trades]
    wins = [r for r in Rs if r > 0]
    losses = [r for r in Rs if r <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    peak, max_dd = curve[0]["equity"], 0.0
    for p in curve:
        peak = max(peak, p["equity"])
        max_dd = max(max_dd, (peak - p["equity"]) / peak)

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": 100.0 * len(wins) / len(trades),
        "avg_R": sum(Rs) / len(Rs),
        "avg_win_R": (gross_win / len(wins)) if wins else 0.0,
        "avg_loss_R": (-gross_loss / len(losses)) if losses else 0.0,
        "expectancy_R": sum(Rs) / len(Rs),
        "total_R": sum(Rs),
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "max_dd_pct": 100.0 * max_dd,
        "final_equity": equity,
        "return_pct": 100.0 * (equity - start_equity) / start_equity,
        "curve": curve,
    }
