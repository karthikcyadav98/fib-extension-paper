"""EMA, ATR and fractal swing pivots. Stdlib only, list-in/list-out.

Every function returns a series the same length as the input, with None in
positions where the value is not yet defined. Nothing here looks forward.
"""


def ema(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    k = 2.0 / (period + 1.0)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def atr(bars, period=14):
    """Wilder's ATR."""
    n = len(bars)
    out = [None] * n
    if n < period + 1:
        return out
    trs = [None]
    for i in range(1, n):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    seed = sum(trs[1 : period + 1]) / period
    out[period] = seed
    prev = seed
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + trs[i]) / period
        out[i] = prev
    return out


def pivots(bars, left=3, right=3):
    """Fractal swing points.

    A pivot high at index i needs `left` lower highs before and `right` lower
    highs after. It is therefore only KNOWABLE at index i + right, which is what
    `confirm_idx` records -- the strategy must never use a pivot before then.

    Returns (highs, lows) as lists of
      {"idx": i, "price": p, "confirm_idx": i + right}
    """
    hi, lo = [], []
    n = len(bars)
    for i in range(left, n - right):
        h = bars[i]["high"]
        l = bars[i]["low"]
        is_h = all(bars[j]["high"] < h for j in range(i - left, i)) and all(
            bars[j]["high"] <= h for j in range(i + 1, i + right + 1)
        )
        is_l = all(bars[j]["low"] > l for j in range(i - left, i)) and all(
            bars[j]["low"] >= l for j in range(i + 1, i + right + 1)
        )
        if is_h:
            hi.append({"idx": i, "price": h, "confirm_idx": i + right})
        if is_l:
            lo.append({"idx": i, "price": l, "confirm_idx": i + right})
    return hi, lo
