"""Traded universe.

The live system is FOREX ONLY, on 4h bars resampled from Yahoo's 1h feed
(Yahoo has no native 4h interval).

Why 4h and not 1h: at 1h the fib stop sits ~0.10% from entry, the same order of
magnitude as the spread, so cost consumed the move -- measured at -0.048R over
405 trades. At 4h the stop is ~0.23% wide and the drag roughly halves, to
+0.006R. That is breakeven, not an edge; it is a cost-structure fix.

16 pairs rather than 4, because a 4-pair book produces ~0.13 signals/day and a
live test would collect almost no data. The crosses also dilute USD
concentration, which matters -- see `exposure` below.

cost_bps is ONE-WAY and all-in (typical retail spread + commission + slippage).
Majors are tight; JPY and AUD crosses are materially wider, and that difference
is large relative to the strategy's edge, so it is not averaged away.

`base`/`quote` drive the currency-exposure cap in paper.py. Sixteen FX pairs are
not sixteen independent bets: six USD-quoted longs are one leveraged USD short.
"""

FOREX = [
    # --- majors ---
    {"id": "EURUSD", "base": "EUR", "quote": "USD", "cost_bps": 0.5},
    {"id": "USDJPY", "base": "USD", "quote": "JPY", "cost_bps": 0.5},
    {"id": "GBPUSD", "base": "GBP", "quote": "USD", "cost_bps": 0.7},
    {"id": "AUDUSD", "base": "AUD", "quote": "USD", "cost_bps": 0.8},
    {"id": "USDCHF", "base": "USD", "quote": "CHF", "cost_bps": 0.9},
    {"id": "USDCAD", "base": "USD", "quote": "CAD", "cost_bps": 0.9},
    {"id": "NZDUSD", "base": "NZD", "quote": "USD", "cost_bps": 1.2},
    # --- crosses ---
    {"id": "EURGBP", "base": "EUR", "quote": "GBP", "cost_bps": 1.0},
    {"id": "EURJPY", "base": "EUR", "quote": "JPY", "cost_bps": 1.0},
    {"id": "EURCHF", "base": "EUR", "quote": "CHF", "cost_bps": 1.2},
    {"id": "AUDJPY", "base": "AUD", "quote": "JPY", "cost_bps": 1.3},
    {"id": "CADJPY", "base": "CAD", "quote": "JPY", "cost_bps": 1.5},
    {"id": "EURAUD", "base": "EUR", "quote": "AUD", "cost_bps": 1.6},
    {"id": "GBPJPY", "base": "GBP", "quote": "JPY", "cost_bps": 1.8},
    {"id": "CHFJPY", "base": "CHF", "quote": "JPY", "cost_bps": 1.8},
    {"id": "GBPAUD", "base": "GBP", "quote": "AUD", "cost_bps": 2.2},
]

UNIVERSE = [
    dict(market="forex", source="yahoo", symbol=f"{f['id']}=X",
         interval="1h", range="730d", resample=4, **f)
    for f in FOREX
]

# Kept only so the backtest can still compare markets; not traded live.
REFERENCE = [
    {"id": "BTCUSDT", "market": "crypto", "source": "binance", "symbol": "BTCUSDT", "kraken_symbol": "XBTUSD", "interval": "4h", "limit": 6000, "cost_bps": 5.5},
    {"id": "ETHUSDT", "market": "crypto", "source": "binance", "symbol": "ETHUSDT", "kraken_symbol": "ETHUSD", "interval": "4h", "limit": 6000, "cost_bps": 5.5},
    {"id": "NIFTY", "market": "india", "source": "yahoo", "symbol": "^NSEI", "interval": "1d", "range": "5y", "cost_bps": 4.0},
    {"id": "RELIANCE", "market": "india", "source": "yahoo", "symbol": "RELIANCE.NS", "interval": "1d", "range": "5y", "cost_bps": 6.0},
]

BY_ID = {i["id"]: i for i in UNIVERSE}
MARKETS = ["forex"]


def for_market(market):
    return [i for i in UNIVERSE if i["market"] == market]


def currencies(inst):
    return (inst["base"], inst["quote"])
