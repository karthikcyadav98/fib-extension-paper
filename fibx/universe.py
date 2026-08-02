"""Traded universe, split by market so we can compare Indian / forex / crypto.

Timeframe choice is deliberate, not arbitrary:
  forex  1h  -- deep liquidity, 24/5 continuity, cleanest swing structure
  crypto 4h  -- strongest trends but noisiest stops; slower TF to survive wicks
  india  1d  -- overnight gaps destroy intraday swing structure, so positional only
"""

UNIVERSE = [
    # ---- forex (Yahoo, keyless) ----
    {"id": "EURUSD", "market": "forex", "source": "yahoo", "symbol": "EURUSD=X", "interval": "1h", "range": "730d", "cost_bps": 0.6},
    {"id": "GBPUSD", "market": "forex", "source": "yahoo", "symbol": "GBPUSD=X", "interval": "1h", "range": "730d", "cost_bps": 0.8},
    {"id": "USDJPY", "market": "forex", "source": "yahoo", "symbol": "USDJPY=X", "interval": "1h", "range": "730d", "cost_bps": 0.6},
    {"id": "AUDUSD", "market": "forex", "source": "yahoo", "symbol": "AUDUSD=X", "interval": "1h", "range": "730d", "cost_bps": 1.0},
    # ---- crypto (Binance, keyless; Kraken fallback for US/CI runners) ----
    {"id": "BTCUSDT", "market": "crypto", "source": "binance", "symbol": "BTCUSDT", "kraken_symbol": "XBTUSD", "interval": "4h", "limit": 6000, "cost_bps": 5.5},
    {"id": "ETHUSDT", "market": "crypto", "source": "binance", "symbol": "ETHUSDT", "kraken_symbol": "ETHUSD", "interval": "4h", "limit": 6000, "cost_bps": 5.5},
    {"id": "SOLUSDT", "market": "crypto", "source": "binance", "symbol": "SOLUSDT", "kraken_symbol": "SOLUSD", "interval": "4h", "limit": 6000, "cost_bps": 6.5},
    {"id": "BNBUSDT", "market": "crypto", "source": "binance", "symbol": "BNBUSDT", "kraken_symbol": "BNBUSD", "interval": "4h", "limit": 6000, "cost_bps": 6.0},
    # ---- india (Yahoo, keyless) ----
    {"id": "NIFTY", "market": "india", "source": "yahoo", "symbol": "^NSEI", "interval": "1d", "range": "5y", "cost_bps": 4.0},
    {"id": "RELIANCE", "market": "india", "source": "yahoo", "symbol": "RELIANCE.NS", "interval": "1d", "range": "5y", "cost_bps": 6.0},
    {"id": "HDFCBANK", "market": "india", "source": "yahoo", "symbol": "HDFCBANK.NS", "interval": "1d", "range": "5y", "cost_bps": 6.0},
    {"id": "INFY", "market": "india", "source": "yahoo", "symbol": "INFY.NS", "interval": "1d", "range": "5y", "cost_bps": 6.0},
    {"id": "TCS", "market": "india", "source": "yahoo", "symbol": "TCS.NS", "interval": "1d", "range": "5y", "cost_bps": 6.0},
]

BY_ID = {i["id"]: i for i in UNIVERSE}
MARKETS = ["forex", "crypto", "india"]


def for_market(market):
    return [i for i in UNIVERSE if i["market"] == market]
