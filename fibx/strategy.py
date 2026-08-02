"""Trend-Based Fibonacci Extension -- made fully mechanical.

The discretionary version of this strategy is untestable because every trader
picks different swings. Here the three anchor points are chosen by a fixed rule,
so the same chart always produces the same trade.

  P1  confirmed swing low      (impulse origin)
  P2  confirmed swing high     (impulse peak)      after P1
  P3  confirmed swing low      (pullback trough)   after P2, and P3 > P1

  leg      = P2 - P1
  retrace  = (P2 - P3) / leg           must sit in [0.236, 0.786]
  T1       = P3 + 1.272 * leg
  T2       = P3 + 1.618 * leg
  stop     = P3 - stop_atr_mult * ATR

Filters
  trend    close > EMA50 > EMA200          (mirrored for shorts)
  trigger  first close above the prior bar's high, within `entry_window`
           bars of P3's confirmation -- i.e. the pullback is actually resolving
  quality  reward-to-risk to T1 must be >= min_rr

Every pivot is used only from its `confirm_idx` onward, so no signal can be
generated from information that had not printed yet.
"""

from .indicators import atr, ema, pivots

# NOTE ON THESE DEFAULTS
# stop_atr_mult / min_rr / pivot / entry_window are the BEST cell out of the
# 72-config sweep in robustness.py (avg +0.002R, i.e. exactly breakeven). They
# are therefore optimistic by selection: they were chosen after seeing the
# results. The median cell is about -0.12R. Treat live results from these
# settings as an upper bound, not an expectation.
DEFAULTS = {
    "pivot_left": 5,
    "pivot_right": 5,
    "ema_fast": 50,
    "ema_slow": 200,
    "atr_period": 14,
    "stop_atr_mult": 1.5,
    "retrace_min": 0.236,
    "retrace_max": 0.786,
    "ext_t1": 1.272,
    "ext_t2": 1.618,
    "entry_window": 10,    # bars after P3 confirmation to still accept a trigger
    "min_rr": 2.0,         # reward:risk to T1
    "allow_short": True,
    "max_bars_in_trade": 60,
}


def config(**overrides):
    cfg = dict(DEFAULTS)
    cfg.update(overrides)
    return cfg


def _latest_before(pivots_by_idx, idxs, limit_idx, t):
    """Newest pivot with idx < limit_idx that is already confirmed at bar t."""
    import bisect

    k = bisect.bisect_left(idxs, limit_idx) - 1
    while k >= 0:
        p = pivots_by_idx[k]
        if p["confirm_idx"] <= t:
            return p
        k -= 1
    return None


def _pick_anchors(highs, lows, hi_idx, lo_idx, t, side, window):
    """Newest valid (P1, P2, P3) triple whose pivots are all confirmed by bar t.

    P3 must have been confirmed within `window` bars of t -- the pullback has to
    be resolving now, not 40 bars ago -- which also keeps this cheap.
    """
    if side == "long":
        third, second, first = lows, highs, lows
        third_idx, second_idx, first_idx_ = lo_idx, hi_idx, lo_idx
    else:
        third, second, first = highs, lows, highs
        third_idx, second_idx, first_idx_ = hi_idx, lo_idx, hi_idx

    for p3 in reversed(third):
        if p3["confirm_idx"] > t:
            continue
        if t - p3["confirm_idx"] > window:
            break  # older pivots are only further out of the window
        p2 = _latest_before(second, second_idx, p3["idx"], t)
        if not p2:
            continue
        p1 = _latest_before(first, first_idx_, p2["idx"], t)
        if not p1:
            continue

        leg = (p2["price"] - p1["price"]) if side == "long" else (p1["price"] - p2["price"])
        if leg <= 0:
            continue
        # Pullback must hold above the impulse origin -- a higher low (lower high
        # for shorts). If it breaks P1 the trend leg is void, not a pullback.
        if side == "long" and p3["price"] <= p1["price"]:
            continue
        if side == "short" and p3["price"] >= p1["price"]:
            continue
        return p1, p2, p3, leg
    return None


def scan(bars, cfg=None, first_idx=0):
    """Return every signal triggered at bar index >= first_idx.

    A signal is an intent to enter at that bar's close. Fills/exits are the
    backtester's or the paper broker's job, not this function's.
    """
    cfg = cfg or config()
    n = len(bars)
    warmup = max(cfg["ema_slow"], cfg["atr_period"]) + cfg["pivot_left"] + cfg["pivot_right"] + 2
    if n <= warmup:
        return []

    closes = [b["close"] for b in bars]
    ef = ema(closes, cfg["ema_fast"])
    es = ema(closes, cfg["ema_slow"])
    a = atr(bars, cfg["atr_period"])
    highs, lows = pivots(bars, cfg["pivot_left"], cfg["pivot_right"])
    hi_idx = [p["idx"] for p in highs]
    lo_idx = [p["idx"] for p in lows]

    signals = []
    used = set()  # (side, p3_idx) -- one trade per pullback

    for t in range(max(warmup, first_idx), n):
        if ef[t] is None or es[t] is None or a[t] is None or a[t] <= 0:
            continue

        sides = []
        if closes[t] > ef[t] > es[t]:
            sides.append("long")
        if cfg["allow_short"] and closes[t] < ef[t] < es[t]:
            sides.append("short")

        for side in sides:
            picked = _pick_anchors(highs, lows, hi_idx, lo_idx, t, side, cfg["entry_window"])
            if not picked:
                continue
            p1, p2, p3, leg = picked
            if (side, p3["idx"]) in used:
                continue

            retr = (p2["price"] - p3["price"]) / leg if side == "long" else (p3["price"] - p2["price"]) / leg
            if not (cfg["retrace_min"] <= retr <= cfg["retrace_max"]):
                continue

            # Momentum trigger: first close taking out the previous bar's extreme.
            if side == "long" and not closes[t] > bars[t - 1]["high"]:
                continue
            if side == "short" and not closes[t] < bars[t - 1]["low"]:
                continue

            entry = closes[t]
            pad = cfg["stop_atr_mult"] * a[t]
            if side == "long":
                stop = p3["price"] - pad
                t1 = p3["price"] + cfg["ext_t1"] * leg
                t2 = p3["price"] + cfg["ext_t2"] * leg
                risk = entry - stop
                reward = t1 - entry
            else:
                stop = p3["price"] + pad
                t1 = p3["price"] - cfg["ext_t1"] * leg
                t2 = p3["price"] - cfg["ext_t2"] * leg
                risk = stop - entry
                reward = entry - t1

            if risk <= 0 or reward <= 0 or reward / risk < cfg["min_rr"]:
                continue

            used.add((side, p3["idx"]))
            signals.append(
                {
                    "idx": t,
                    "ts": bars[t]["ts"],
                    "close_ts": bars[t]["close_ts"],
                    "side": side,
                    "entry": entry,
                    "stop": stop,
                    "t1": t1,
                    "t2": t2,
                    "risk_per_unit": risk,
                    "rr_t1": reward / risk,
                    "rr_t2": (abs(t2 - entry)) / risk,
                    "retrace": retr,
                    "atr": a[t],
                    "p1": {"idx": p1["idx"], "price": p1["price"], "ts": bars[p1["idx"]]["ts"]},
                    "p2": {"idx": p2["idx"], "price": p2["price"], "ts": bars[p2["idx"]]["ts"]},
                    "p3": {"idx": p3["idx"], "price": p3["price"], "ts": bars[p3["idx"]]["ts"]},
                }
            )
    return signals
