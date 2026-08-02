"""Free, no-API-key market data. Stdlib only.

Sources:
  Binance public REST  -> crypto intraday OHLCV
  Yahoo Finance chart  -> forex + Indian equities/indices OHLCV

Both are keyless. Responses are cached on disk with a TTL so repeated runs
during a session don't hammer the endpoints.
"""

import json
import os
import ssl
import time
import urllib.parse
import urllib.request

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")
# Yahoo 429s a full "...Chrome/120...Safari/537.36" UA but serves a short one.
# Do not "improve" this into a more realistic browser string -- it will break.
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

BINANCE_HOSTS = ["https://api.binance.com", "https://data-api.binance.vision"]
YAHOO_HOSTS = ["https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"]


class DataError(Exception):
    pass


def _ssl_context():
    """python.org builds ship no CA bundle; fall back to certifi or the macOS one."""
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca", 0) > 0:
        return ctx
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for path in ("/etc/ssl/cert.pem", "/usr/local/etc/openssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"):
        if os.path.exists(path):
            return ssl.create_default_context(cafile=path)
    raise DataError("no CA bundle found -- run Python's 'Install Certificates.command' or pip install certifi")


_SSL = None


_LAST_CALL = {}
MIN_GAP = {"query1.finance.yahoo.com": 1.5, "query2.finance.yahoo.com": 1.5}


def _throttle(url):
    """Yahoo 429s on rapid-fire requests; keep a minimum gap per host."""
    host = urllib.parse.urlparse(url).netloc
    gap = MIN_GAP.get(host, 0.15)
    wait = gap - (time.time() - _LAST_CALL.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _LAST_CALL[host] = time.time()


def _get(url, timeout=20, retries=4):
    global _SSL
    if _SSL is None:
        _SSL = _ssl_context()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json,text/plain,*/*"})
    delay = 2.0
    for attempt in range(retries):
        _throttle(url)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 999) and attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except urllib.error.URLError:
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise DataError(f"exhausted retries for {url}")


def _cache_path(key):
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
    return os.path.join(CACHE_DIR, safe + ".json")


def _cached(key, ttl, producer):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(key)
    if ttl > 0 and os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < ttl:
            try:
                with open(path) as f:
                    return json.load(f)
            except (ValueError, OSError):
                pass
    value = producer()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(value, f)
    os.replace(tmp, path)
    return value


# --------------------------------------------------------------------------
# Bars are dicts: {ts (ms, bar OPEN time), open, high, low, close, volume}
# Only CLOSED bars are ever returned -- the forming bar is dropped so the
# strategy can never see a price that had not yet printed.
# --------------------------------------------------------------------------


def fetch_binance(symbol, interval="4h", limit=1000, ttl=300):
    """Crypto OHLCV from Binance. symbol e.g. 'BTCUSDT', interval '1h','4h','1d'."""

    def page(host, end_ms):
        url = f"{host}/api/v3/klines?symbol={symbol}&interval={interval}&limit=1000"
        if end_ms:
            url += f"&endTime={int(end_ms)}"
        raw = json.loads(_get(url))
        if not isinstance(raw, list):
            raise DataError(f"binance unexpected payload for {symbol}: {str(raw)[:160]}")
        return [
            {
                "ts": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "close_ts": int(k[6]),
            }
            for k in raw
        ]

    def go():
        # Binance caps a request at 1000 klines, so page backwards for deep history.
        last_err = None
        for host in BINANCE_HOSTS:
            try:
                out, end_ms = [], None
                while len(out) < limit:
                    chunk = page(host, end_ms)
                    if not chunk:
                        break
                    out = chunk + out
                    end_ms = chunk[0]["ts"] - 1
                    if len(chunk) < 1000:
                        break
                now_ms = time.time() * 1000
                bars = [b for b in out if b["close_ts"] <= now_ms]
                if not bars:
                    raise DataError(f"binance returned no closed bars for {symbol}")
                return bars[-limit:]
            except Exception as e:
                last_err = e
                continue
        raise DataError(f"binance fetch failed for {symbol}: {last_err}")

    return _cached(f"binance_{symbol}_{interval}_{limit}", ttl, go)


def fetch_yahoo(symbol, interval="1d", rng="2y", ttl=300):
    """Forex / equities / indices OHLCV from Yahoo's chart endpoint."""

    def go():
        enc = urllib.parse.quote(symbol, safe="")
        last_err = None
        for host in YAHOO_HOSTS:
            url = f"{host}/v8/finance/chart/{enc}?range={rng}&interval={interval}&includePrePost=false"
            try:
                payload = json.loads(_get(url))
            except Exception as e:
                last_err = e
                continue
            chart = payload.get("chart") or {}
            if chart.get("error"):
                last_err = DataError(f"yahoo error for {symbol}: {chart['error']}")
                continue
            results = chart.get("result") or []
            if not results:
                last_err = DataError(f"yahoo empty result for {symbol}")
                continue
            res = results[0]
            stamps = res.get("timestamp") or []
            q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
            o, h, l, c = q.get("open"), q.get("high"), q.get("low"), q.get("close")
            if not stamps or not all([o, h, l, c]):
                last_err = DataError(f"yahoo missing OHLC for {symbol}")
                continue
            v = q.get("volume") or [0] * len(stamps)
            step = _interval_ms(interval)
            bars = []
            for i, t in enumerate(stamps):
                # Yahoo pads gaps with nulls; skip any incomplete bar.
                if None in (o[i], h[i], l[i], c[i]):
                    continue
                bars.append(
                    {
                        "ts": int(t) * 1000,
                        "open": float(o[i]),
                        "high": float(h[i]),
                        "low": float(l[i]),
                        "close": float(c[i]),
                        "volume": float(v[i] or 0),
                        "close_ts": int(t) * 1000 + step - 1,
                    }
                )
            now_ms = time.time() * 1000
            return [b for b in bars if b["close_ts"] <= now_ms]
        raise DataError(f"yahoo fetch failed for {symbol}: {last_err}")

    return _cached(f"yahoo_{symbol}_{interval}_{rng}", ttl, go)


_MS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400, "1wk": 604800}


def _interval_ms(interval):
    return _MS.get(interval, 86400) * 1000


KRAKEN_INTERVAL = {"1h": 60, "4h": 240, "1d": 1440}


def fetch_kraken(pair, interval="4h", ttl=300):
    """Crypto OHLCV from Kraken.

    Exists because Binance returns HTTP 451 to US IPs, which is what GitHub
    Actions runners have -- without this the crypto feed dies in CI. Kraken
    caps the response at ~720 bars, plenty for live trading (EMA200 on 4h needs
    ~260) but not for the deep backtest, which still uses Binance locally.
    """

    def go():
        mins = KRAKEN_INTERVAL.get(interval)
        if not mins:
            raise DataError(f"kraken has no {interval} interval")
        url = f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval={mins}"
        payload = json.loads(_get(url))
        if payload.get("error"):
            raise DataError(f"kraken error for {pair}: {payload['error']}")
        result = payload.get("result") or {}
        key = next((k for k in result if k != "last"), None)
        if not key:
            raise DataError(f"kraken empty result for {pair}")
        step = mins * 60
        bars = [
            {
                "ts": int(r[0]) * 1000,
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": float(r[6]),
                "close_ts": (int(r[0]) + step) * 1000 - 1,
            }
            for r in result[key]
        ]
        now_ms = time.time() * 1000
        return [b for b in bars if b["close_ts"] <= now_ms]

    return _cached(f"kraken_{pair}_{interval}", ttl, go)


def fetch(instrument, ttl=300):
    """Dispatch on an instrument spec from universe.py, with failover."""
    src = instrument["source"]
    if src == "yahoo":
        return fetch_yahoo(instrument["symbol"], instrument["interval"], instrument.get("range", "2y"), ttl)
    if src == "binance":
        try:
            return fetch_binance(instrument["symbol"], instrument["interval"], instrument.get("limit", 1000), ttl)
        except Exception as primary:
            alt = instrument.get("kraken_symbol")
            if not alt:
                raise
            try:
                return fetch_kraken(alt, instrument["interval"], ttl)
            except Exception as secondary:
                raise DataError(f"binance failed ({primary}); kraken fallback failed ({secondary})")
    raise DataError(f"unknown source {src}")
