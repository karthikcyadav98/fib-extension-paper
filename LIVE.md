# Going properly live

What runs today is an *hourly batch* against Yahoo 1h bars resampled to 4h.
It is honest paper trading, but it is not streaming, and it simulates fills
internally rather than sending orders anywhere.

## What each option actually buys you

| Option | Live prices | Real order execution | Cost | Key needed |
|---|---|---|---|---|
| **OANDA practice** | yes, streaming | **yes** — real demo account | free | account token |
| Twelve Data free | yes (quote/1min) | no | free, 800 req/day | API key |
| Yahoo (today) | no, ~55 min stale | no | free | none |
| TradingView | — | — | — | **no public data or execution API exists** |

**OANDA practice is the only one that gives both.** Orders are really submitted,
really filled at real spreads, and really tracked by a broker — the simulation
guesswork in `backtest._fill` disappears entirely.

## Getting the token (about 2 minutes)

1. oanda.com -> "Try a free demo"
2. Sign in -> **Manage API Access**
3. Generate a **practice** token, and note the account id (`101-...`)
4. Put them in GitHub repo secrets as `OANDA_TOKEN` and `OANDA_ACCOUNT`

Nothing goes in the code, and a practice token cannot touch real money.

## What changes once it exists

- `fibx/data.py` gains an OANDA candles source: real 4h FX candles, no resampling
  and no weekend-bucketing workaround
- `fibx/paper.py` submits real orders with bracket stop/target instead of
  simulating fills, so slippage and spread become measured rather than assumed
- the dashboard shows broker-confirmed fills

## On TradingView

There is no free (or paid) public TradingView API for market data or order
execution — it is a charting and social product. Their open-source
`lightweight-charts` library is only a renderer; it needs a data feed behind it.
So TradingView cannot be the data source here. The candlestick view in the
dashboard is drawn directly in SVG for that reason.
