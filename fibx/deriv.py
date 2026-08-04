"""Deriv market-data client -- stdlib only, no token, works from India.

OANDA refuses Indian residents, which ruled out the usual "free demo account
with a REST API" route. Deriv accepts Indian clients and, more usefully here,
serves historical candles and live ticks over a public WebSocket with no
authentication at all.

Why this beats the Yahoo feed it replaces:
  * genuine broker 4h candles, so no resampling and no weekend-bucket workaround
  * live tick prices, so the dashboard can show a real current price rather than
    a bar that closed up to an hour ago
  * no API key, no rate-limit ceiling, no geo-restriction

Implemented against raw sockets because the project has no dependencies. Only
the small slice of RFC 6455 needed for short client messages is here: text
frames, client masking, and the 7/16/64-bit payload lengths.
"""

import base64
import json
import os
import socket
import ssl
import struct
import time

HOST = "ws.derivws.com"
PATH = "/websockets/v3?app_id=1"          # public app id, read-only market data
GRANULARITY = {"1h": 3600, "4h": 14400, "1d": 86400}
MAX_COUNT = 5000                           # server cap per request


class DerivError(Exception):
    pass


def _ctx():
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca", 0) > 0:
        return ctx
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for p in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"):
        if os.path.exists(p):
            return ssl.create_default_context(cafile=p)
    raise DerivError("no CA bundle available")


class _WS:
    """Single-shot WebSocket connection: connect, send one request, read reply."""

    def __init__(self, timeout=25):
        key = base64.b64encode(os.urandom(16)).decode()
        raw = socket.create_connection((HOST, 443), timeout=timeout)
        self.s = _ctx().wrap_socket(raw, server_hostname=HOST)
        self.s.send((
            f"GET {PATH} HTTP/1.1\r\nHost: {HOST}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        self._buf = bytearray()
        head = self.s.recv(4096).decode("utf-8", "replace")
        if "101" not in head.split("\r\n")[0]:
            raise DerivError(f"handshake failed: {head.splitlines()[0] if head else 'no response'}")

    def send(self, obj):
        msg = json.dumps(obj).encode()
        n = len(msg)
        hdr = bytearray([0x81])                     # FIN + text frame
        if n < 126:
            hdr += bytearray([0x80 | n])
        elif n < 65536:
            hdr += bytearray([0x80 | 126]) + struct.pack(">H", n)
        else:
            hdr += bytearray([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)                        # clients MUST mask
        hdr += mask
        self.s.send(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(msg)))

    def recv(self):
        """Read one frame, KEEPING any trailing bytes for the next call.

        The buffer has to live on the connection, not in this method. A single
        TCP read can carry the tail of one frame and the head of the next; if
        that remainder is dropped, the following read starts mid-frame, parses
        a garbage length and blocks forever. Harmless on a one-shot socket,
        fatal once the connection is reused.
        """
        while True:
            while len(self._buf) >= 2:
                b0, b1 = self._buf[0], self._buf[1]
                ln = b1 & 0x7F
                i = 2
                if ln == 126:
                    if len(self._buf) < 4:
                        break
                    ln = struct.unpack(">H", self._buf[2:4])[0]
                    i = 4
                elif ln == 127:
                    if len(self._buf) < 10:
                        break
                    ln = struct.unpack(">Q", self._buf[2:10])[0]
                    i = 10
                if len(self._buf) < i + ln:
                    break
                payload = self._buf[i:i + ln]
                self._buf = self._buf[i + ln:]          # keep the remainder
                op = b0 & 0x0F
                if op == 0x8:
                    raise DerivError("server closed the connection")
                if op == 0x9:                            # ping -> pong
                    hdr = bytearray([0x8A, 0x80 | len(payload)])
                    m = os.urandom(4)
                    self.s.send(bytes(hdr + m) + bytes(c ^ m[j % 4] for j, c in enumerate(payload)))
                    continue
                if op == 0xA:                            # pong, ignore
                    continue
                return json.loads(payload.decode("utf-8", "replace"))

            chunk = self.s.recv(65536)
            if not chunk:
                raise DerivError("connection closed before a full frame arrived")
            self._buf += chunk

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


_session = None
_req_id = 0


def _request(payload, _retry=True):
    """Send one request on a REUSED connection.

    Opening a fresh TLS+WebSocket handshake per request meant ~48 handshakes to
    refresh 16 pairs, which dominated the runtime. One long-lived socket carries
    them all; req_id keeps replies matched to requests.
    """
    global _session, _req_id
    if _session is None:
        _session = _WS()
    _req_id += 1
    rid = _req_id
    payload = dict(payload, req_id=rid)
    try:
        _session.send(payload)
        # Skip anything that is not the reply we asked for (stray subscription
        # pushes) rather than mistaking it for our answer.
        for _ in range(20):
            reply = _session.recv()
            if reply.get("req_id") == rid:
                break
        else:
            raise DerivError("no matching reply")
    except Exception:
        try:
            _session.close()
        except Exception:
            pass
        _session = None
        if _retry:
            return _request(payload, _retry=False)
        raise
    if isinstance(reply, dict) and reply.get("error"):
        raise DerivError(reply["error"].get("message", "unknown error"))
    return reply


def close():
    global _session
    if _session is not None:
        _session.close()
        _session = None


def candles(pair, interval="4h", count=800):
    """Historical OHLC. `pair` is a plain code like 'EURUSD'.

    Deriv caps a single response, so older blocks are pulled by walking the
    `end` cursor backwards until the server stops yielding new bars.
    """
    gran = GRANULARITY.get(interval)
    if not gran:
        raise DerivError(f"unsupported interval {interval}")

    collected = {}
    end = "latest"
    while len(collected) < count:
        reply = _request({
            "ticks_history": f"frx{pair}",
            "style": "candles",
            "granularity": gran,
            "count": min(MAX_COUNT, count),
            "end": end,
        })
        chunk = reply.get("candles") or []
        fresh = [c for c in chunk if c["epoch"] not in collected]
        if not fresh:
            break
        for c in fresh:
            collected[c["epoch"]] = c
        end = str(min(c["epoch"] for c in chunk) - 1)

    now = time.time()
    out = []
    for e in sorted(collected):
        c = collected[e]
        # Only closed candles: the in-progress one would let the strategy see a
        # price that has not finished printing.
        if e + gran > now:
            continue
        out.append({
            "ts": e * 1000,
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "volume": 0.0,
            "close_ts": (e + gran) * 1000 - 1,
        })
    return out[-count:]


def tick(pair):
    """Latest live quote -- the real current price, not a stale bar close."""
    reply = _request({"ticks_history": f"frx{pair}", "count": 1, "end": "latest"})
    hist = reply.get("history") or {}
    prices, times = hist.get("prices") or [], hist.get("times") or []
    if not prices:
        raise DerivError(f"no tick for {pair}")
    return {"price": float(prices[-1]), "ts": int(times[-1]) * 1000}
