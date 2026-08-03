"""Live paper-trading broker. Starts at $1000, persists to state/portfolio.json.

Designed to be run repeatedly (cron, loop, by hand). Each run:
  1. pulls fresh bars for every instrument
  2. advances any open position through the bars that closed since last run
  3. looks for a new signal on the newest closed bar

It is idempotent per bar: every symbol records the timestamp of the last bar it
processed, so re-running twice in a minute cannot double-trade or double-count.
Exit rules and fill assumptions are identical to backtest.py, so the live run and
the backtest are measuring the same strategy.
"""

import json
import os
import time

from . import data, strategy, universe
from .backtest import _fill

STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state")
STATE_PATH = os.path.join(STATE_DIR, "portfolio.json")

START_EQUITY = 1000.0
RISK_PCT = 0.01          # 1% of equity risked per trade
MAX_POSITIONS = 8
MAX_NOTIONAL_PCT = 0.35  # cap any single position's notional
MAX_CCY_EXPOSURE = 3     # net open positions exposed to any one currency

def _exposure(positions):
    """Net directional exposure per currency across open positions.

    Long EURUSD is long EUR and short USD. Without this, a trend-following book
    can hold six USD-quoted longs and believe it has six positions when it has
    one leveraged USD short -- the single most common way an FX book dies.
    """
    net = {}
    for p in positions:
        if not p.get("base"):
            continue
        d = 1 if p["side"] == "long" else -1
        net[p["base"]] = net.get(p["base"], 0) + d
        net[p["quote"]] = net.get(p["quote"], 0) - d
    return net


def _would_breach(positions, inst, side):
    d = 1 if side == "long" else -1
    net = _exposure(positions)
    net[inst["base"]] = net.get(inst["base"], 0) + d
    net[inst["quote"]] = net.get(inst["quote"], 0) - d
    return any(abs(v) > MAX_CCY_EXPOSURE for v in net.values())


def new_state():
    return {
        "start_equity": START_EQUITY,
        "equity": START_EQUITY,
        "realised_pnl": 0.0,
        "risk_pct": RISK_PCT,
        "started_at": int(time.time() * 1000),
        "last_update": None,
        "positions": [],
        "closed": [],
        "equity_curve": [],
        "last_bar": {},
        "signals": [],
        "errors": [],
    }


def load():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return new_state()


def save(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_PATH)


def _open_position(state, inst, sig):
    equity = state["equity"]
    risk_amt = equity * state["risk_pct"]
    qty = risk_amt / sig["risk_per_unit"]
    entry = _fill(sig["entry"], sig["side"], "in", inst["cost_bps"])

    notional = qty * entry
    cap = equity * MAX_NOTIONAL_PCT
    if notional > cap:
        qty *= cap / notional
        notional = cap

    return {
        "id": f"{inst['id']}-{sig['close_ts']}",
        "symbol": inst["id"],
        "market": inst["market"],
        "base": inst.get("base"),
        "quote": inst.get("quote"),
        "side": sig["side"],
        "qty": qty,
        "qty_open": qty,
        "entry": entry,
        "stop": sig["stop"],
        "cur_stop": sig["stop"],
        "t1": sig["t1"],
        "t2": sig["t2"],
        "risk_per_unit": sig["risk_per_unit"],
        "risk_amt": qty * sig["risk_per_unit"],
        "notional": notional,
        "opened_ts": sig["close_ts"],
        "opened_bar_ts": sig["ts"],
        "bars_held": 0,
        "realised": 0.0,
        "R": 0.0,
        "scaled_t1": False,
        "retrace": sig["retrace"],
        "rr_t1": sig["rr_t1"],
        "anchors": {"p1": sig["p1"], "p2": sig["p2"], "p3": sig["p3"]},
        "fills": [],
        "last_price": entry,
    }


def _advance(pos, bar, cost_bps, max_bars):
    """Push one open position through one closed bar. Returns realised $ delta."""
    side = pos["side"]
    delta = 0.0
    pos["bars_held"] += 1
    pos["last_price"] = bar["close"]

    def close_out(px, frac_qty, kind):
        nonlocal delta
        fill = _fill(px, side, "out", cost_bps)
        pnl = (fill - pos["entry"]) * frac_qty if side == "long" else (pos["entry"] - fill) * frac_qty
        delta += pnl
        pos["realised"] += pnl
        pos["qty_open"] -= frac_qty
        pos["fills"].append({"kind": kind, "ts": bar["ts"], "price": fill, "qty": frac_qty, "pnl": pnl})

    stop = pos["cur_stop"]
    hit_stop = bar["low"] <= stop if side == "long" else bar["high"] >= stop

    if hit_stop:
        gapped = (side == "long" and bar["open"] < stop) or (side == "short" and bar["open"] > stop)
        close_out(bar["open"] if gapped else stop, pos["qty_open"], "breakeven" if pos["scaled_t1"] else "stop")
        pos["status"] = "closed"
        pos["exit_reason"] = "breakeven" if pos["scaled_t1"] else "stop"
        pos["closed_ts"] = bar["close_ts"]
        return delta

    if not pos["scaled_t1"]:
        if (bar["high"] >= pos["t1"]) if side == "long" else (bar["low"] <= pos["t1"]):
            close_out(pos["t1"], pos["qty"] * 0.5, "t1")
            pos["scaled_t1"] = True
            pos["cur_stop"] = pos["entry"]  # breakeven on the runner

    if pos["scaled_t1"] and pos["qty_open"] > 1e-12:
        if (bar["high"] >= pos["t2"]) if side == "long" else (bar["low"] <= pos["t2"]):
            close_out(pos["t2"], pos["qty_open"], "t2")
            pos["status"] = "closed"
            pos["exit_reason"] = "target"
            pos["closed_ts"] = bar["close_ts"]
            return delta

    if pos["bars_held"] >= max_bars and pos["qty_open"] > 1e-12:
        close_out(bar["close"], pos["qty_open"], "time")
        pos["status"] = "closed"
        pos["exit_reason"] = "time"
        pos["closed_ts"] = bar["close_ts"]

    return delta


def update(state=None, ttl=120, verbose=True):
    state = state or load()
    cfg = strategy.config()
    state["errors"] = []
    by_symbol = {p["symbol"]: p for p in state["positions"]}
    events = []

    for inst in universe.UNIVERSE:
        try:
            bars = data.fetch(inst, ttl=ttl)
        except Exception as e:
            state["errors"].append(f"{inst['id']}: {e}")
            if verbose:
                print(f"  ! {inst['id']}: {e}")
            continue
        if len(bars) < 260:
            state["errors"].append(f"{inst['id']}: only {len(bars)} bars")
            continue

        last_seen = state["last_bar"].get(inst["id"])

        # First ever run: adopt history without trading it, so the live test
        # starts flat rather than back-filling imaginary trades.
        if last_seen is None:
            state["last_bar"][inst["id"]] = bars[-1]["ts"]
            continue

        new_bars = [b for b in bars if b["ts"] > last_seen]
        if not new_bars:
            continue

        # Replay EVERY bar that printed since the last run, in order -- not just
        # the newest. The runner is hourly but the machine sleeps, so several
        # bars can accumulate between updates; checking only the last one would
        # silently discard entry signals from the bars in between.
        sig_by_ts = {s["ts"]: s for s in strategy.scan(bars, cfg, first_idx=len(bars) - len(new_bars))}

        for b in new_bars:
            pos = by_symbol.get(inst["id"])

            if pos:
                state["equity"] += _advance(pos, b, inst["cost_bps"], cfg["max_bars_in_trade"])
                if pos.get("status") == "closed":
                    pos["R"] = pos["realised"] / pos["risk_amt"] if pos["risk_amt"] else 0.0
                    state["realised_pnl"] += pos["realised"]
                    state["closed"].append(pos)
                    state["positions"] = [p for p in state["positions"] if p["id"] != pos["id"]]
                    by_symbol.pop(inst["id"], None)
                    events.append(f"CLOSE {inst['id']} {pos['side']} {pos['exit_reason']} "
                                  f"R={pos['R']:+.2f} pnl=${pos['realised']:+.2f}")
                else:
                    pos["last_price"] = b["close"]
                continue

            # Flat on this bar: it may open a position. Entry is at this bar's
            # close, so the same bar must not also advance the new position.
            sig = sig_by_ts.get(b["ts"])
            if not sig or len(state["positions"]) >= MAX_POSITIONS:
                continue
            if inst.get("base") and _would_breach(state["positions"], inst, sig["side"]):
                continue
            newpos = _open_position(state, inst, sig)
            newpos["status"] = "open"
            state["positions"].append(newpos)
            by_symbol[inst["id"]] = newpos
            events.append(f"OPEN  {inst['id']} {sig['side']} @ {newpos['entry']:.6g} "
                          f"stop {sig['stop']:.6g} T1 {sig['t1']:.6g} T2 {sig['t2']:.6g}")

        state["last_bar"][inst["id"]] = bars[-1]["ts"]

    # Mark to market
    unreal = 0.0
    for p in state["positions"]:
        px = p["last_price"]
        unreal += (px - p["entry"]) * p["qty_open"] if p["side"] == "long" else (p["entry"] - px) * p["qty_open"]
    state["unrealised_pnl"] = unreal
    state["equity_mtm"] = state["equity"] + unreal
    state["last_update"] = int(time.time() * 1000)
    state["equity_curve"].append({"ts": state["last_update"], "equity": state["equity"],
                                  "equity_mtm": state["equity_mtm"]})
    state["events"] = (state.get("events", []) + events)[-200:]

    if verbose:
        for e in events:
            print("  " + e)
        print(f"  equity ${state['equity']:.2f}  mtm ${state['equity_mtm']:.2f}  "
              f"open {len(state['positions'])}  closed {len(state['closed'])}")
    return state
