"""Traded universe, split by market so we can compare Indian / forex / crypto.

Timeframe choice is deliberate, and two of these were changed after measurement
rather than assumed up front:

  forex  4h  -- resampled from Yahoo's 1h bars (Yahoo has no native 4h).
                1h measured -0.048R over 405 trades: the fib stop sits only
                ~0.10% from entry there, the same order as the spread, so cost
                eats the move. At 4h the stop is ~0.23% wide and the drag
                roughly halves. A cost-structure fix, not a tuned one.
  crypto 4h  -- strongest trends, and the only market whose ATR is comfortably
                larger than its cost. Widened to 10 pairs: it is the least-bad
                market, so it is where extra sample is worth collecting.
  india  1d  -- overnight gaps destroy intraday swing structure. Left as is;
                it yields ~1 setup per 53 days and contributes almost nothing.

cost_bps is ONE-WAY and all-in (spread + commission + slippage).
kraken_symbol is the crypto failover: Binance returns 451 to US IPs, which is
what GitHub Actions runners have.
"""

UNIVERSE = [
    # ---- forex (Yahoo 1h, resampled to 4h) ----
    {"id": "EURUSD", "market": "forex", "source": "yahoo", "symbol": "EURUSD=X", "interval": "1h", "range": "730d", "resample": 4, "cost_bps": 0.6},
    {"id": "GBPUSD", "market": "forex", "source": "yahoo", "symbol": "GBPUSD=X", "interval": "1h", "range": "730d", "resample": 4, "cost_bps": 0.8},
    {"id": "USDJPY", "market": "forex", "source": "yahoo", "symbol": "USDJPY=X", "interval": "1h", "range": "730d", "resample": 4, "cost_bps": 0.6},
    {"id": "AUDUSD", "market": "forex", "source": "yahoo", "symbol": "AUDUSD=X", "interval": "1h", "range": "730d", "resample": 4, "cost_bps": 1.0},

    # ---- crypto (Binance, keyless; Kraken fallback for US/CI runners) ----
    {"id": "BTCUSDT", "market": "crypto", "source": "binance", "symbol": "BTCUSDT", "kraken_symbol": "XBTUSD", "interval": "4h", "limit": 6000, "cost_bps": 5.5},
    {"id": "ETHUSDT", "market": "crypto", "source": "binance", "symbol": "ETHUSDT", "kraken_symbol": "ETHUSD", "interval": "4h", "limit": 6000, "cost_bps": 5.5},
    {"id": "SOLUSDT", "market": "crypto", "source": "binance", "symbol": "SOLUSDT", "kraken_symbol": "SOLUSD", "interval": "4h", "limit": 6000, "cost_bps": 6.5},
    {"id": "BNBUSDT", "market": "crypto", "source": "binance", "symbol": "BNBUSDT", "kraken_symbol": "BNBUSD", "interval": "4h", "limit": 6000, "cost_bps": 6.0},
    {"id": "XRPUSDT", "market": "crypto", "source": "binance", "symbol": "XRPUSDT", "kraken_symbol": "XRPUSD", "interval": "4h", "limit": 6000, "cost_bps": 6.0},
    {"id": "ADAUSDT", "market": "crypto", "source": "binance", "symbol": "ADAUSDT", "kraken_symbol": "ADAUSD", "interval": "4h", "limit": 6000, "cost_bps": 6.5},
    {"id": "LINKUSDT", "market": "crypto", "source": "binance", "symbol": "LINKUSDT", "kraken_symbol": "LINKUSD", "interval": "4h", "limit": 6000, "cost_bps": 6.5},
    {"id": "DOTUSDT", "market": "crypto", "source": "binance", "symbol": "DOTUSDT", "kraken_symbol": "DOTUSD", "interval": "4h", "limit": 6000, "cost_bps": 7.0},
    {"id": "AVAXUSDT", "market": "crypto", "source": "binance", "symbol": "AVAXUSDT", "kraken_symbol": "AVAXUSD", "interval": "4h", "limit": 6000, "cost_bps": 7.0},
    {"id": "LTCUSDT", "market": "crypto", "source": "binance", "symbol": "LTCUSDT", "kraken_symbol": "LTCUSD", "interval": "4h", "limit": 6000, "cost_bps": 6.0},

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
