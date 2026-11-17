"""Market data providers.

- BinanceProvider: real-time crypto candles (public REST, no API key).
- YahooProvider:   stocks / indices / forex / commodities worldwide via yfinance (often 15-20 min delayed).
- DemoProvider:    synthetic but realistic candles + live ticks, works offline.

`get_provider()` picks per symbol and falls back to demo when the real source fails,
returning a `source` string so the UI can show honestly where data came from.
"""
from __future__ import annotations

import hashlib
import math
import os
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .markets import CRYPTO, DEMO_BASE

INTERVAL_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800}


@dataclass
class Candles:
    symbol: str
    interval: str
    source: str            # "binance" | "yahoo" | "demo"
    delayed: bool          # True if source is typically delayed
    rows: list[dict]       # [{time, open, high, low, close, volume}]

    def to_frame(self) -> pd.DataFrame:
        df = pd.DataFrame(self.rows)
        if df.empty:
            return df
        df.index = pd.to_datetime(df["time"], unit="s")
        return df


class _TTLCache:
    def __init__(self):
        self._d: dict = {}

    def get(self, key, ttl):
        v = self._d.get(key)
        if v and time.time() - v[0] < ttl:
            return v[1]
        return None

    def set(self, key, value):
        self._d[key] = (time.time(), value)


_cache = _TTLCache()


# ---------------------------------------------------------------- Binance
class BinanceProvider:
    name = "binance"
    URL = "https://api.binance.com/api/v3/klines"
    MAP = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"}

    @staticmethod
    def pair(symbol: str) -> str:
        return symbol.replace("-USD", "USDT").replace("-", "")

    def candles(self, symbol: str, interval: str, limit: int = 500) -> Candles:
        import httpx
        r = httpx.get(self.URL, params={"symbol": self.pair(symbol), "interval": self.MAP[interval],
                                        "limit": limit}, timeout=8)
        r.raise_for_status()
        rows = [{"time": int(k[0] // 1000), "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
                 "close": float(k[4]), "volume": float(k[5])} for k in r.json()]
        return Candles(symbol, interval, self.name, False, rows)


# ---------------------------------------------------------------- Yahoo
class YahooProvider:
    name = "yahoo"
    # yfinance interval -> max lookback period it allows
    MAP = {"1m": ("1m", "5d"), "5m": ("5m", "30d"), "15m": ("15m", "55d"), "1h": ("60m", "700d"),
           "4h": ("60m", "700d"), "1d": ("1d", "10y"), "1w": ("1wk", "max")}

    def candles(self, symbol: str, interval: str, limit: int = 500) -> Candles:
        import yfinance as yf
        yf_int, period = self.MAP[interval]
        if interval == "1d":   # don't download 10 years just to show a quote
            period = "1mo" if limit <= 20 else "2y" if limit <= 500 else "5y"
        elif limit <= 10:      # live polling: only the newest bars are needed
            period = {"1m": "1d", "5m": "5d", "15m": "5d", "1h": "5d", "4h": "5d", "1w": "1mo"}[interval]
        df = yf.Ticker(symbol).history(period=period, interval=yf_int, auto_adjust=False)
        if df.empty:
            raise RuntimeError(f"Yahoo returned no data for {symbol}")
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        if interval == "4h":
            df = df.resample("4h").agg({"Open": "first", "High": "max", "Low": "min",
                                        "Close": "last", "Volume": "sum"}).dropna()
        df = df.iloc[-limit:]
        idx = df.index.tz_convert("UTC") if df.index.tz is not None else df.index
        rows = [{"time": int(t.timestamp()), "open": float(o), "high": float(h), "low": float(l),
                 "close": float(c), "volume": float(v or 0)}
                for t, (o, h, l, c, v) in zip(idx, df.itertuples(index=False))]
        return Candles(symbol, interval, self.name, True, rows)


# ---------------------------------------------------------------- Demo
class DemoProvider:
    """Deterministic history per symbol + a live random-walk tick so the chart moves offline."""
    name = "demo"

    def __init__(self):
        self._live: dict[tuple, dict] = {}
        self._spot: dict[str, list] = {}     # symbol -> [price, last_update_ts]; shared by all intervals

    def spot(self, symbol: str) -> float:
        """One random-walk 'true price' per symbol so every interval and the watchlist agree."""
        now = time.time()
        if symbol not in self._spot:
            self._spot[symbol] = [float(DEMO_BASE.get(symbol, 100.0)), now]
        s = self._spot[symbol]
        dt = min(now - s[1], 60.0)
        if dt > 0.4:
            sigma = self._vol(symbol) * math.sqrt(dt / (365 * 86400)) * 3   # a bit livelier than reality
            s[0] *= math.exp(np.random.normal(0, sigma))
            s[1] = now
        return s[0]

    @staticmethod
    def _seed(symbol: str, interval: str) -> int:
        return int(hashlib.md5(f"{symbol}|{interval}".encode()).hexdigest()[:8], 16)

    @staticmethod
    def _vol(symbol: str) -> float:
        if symbol in CRYPTO:
            return 0.65
        if symbol.endswith("=X"):
            return 0.08
        if symbol.endswith("=F"):
            return 0.30
        if symbol.startswith("^") or symbol.endswith(".SS"):
            return 0.17
        return 0.30

    def _history(self, symbol: str, interval: str, limit: int) -> list[dict]:
        step = INTERVAL_SECONDS[interval]
        rng = np.random.default_rng(self._seed(symbol, interval))
        sigma = self._vol(symbol) * math.sqrt(step / (365 * 86400))
        n = limit
        # regime-switching drift so trends appear, then scale so the LAST close ~ base price
        drift = np.repeat(rng.normal(0, sigma * 0.15, n // 50 + 1), 50)[:n]
        rets = drift + rng.standard_t(4, n) * sigma / math.sqrt(2)
        closes = np.exp(np.cumsum(rets))
        closes *= self.spot(symbol) / closes[-1]
        opens = np.r_[closes[0], closes[:-1]] * (1 + rng.normal(0, sigma * 0.2, n))
        span = np.abs(rng.normal(0, sigma * 0.8, n)) * closes
        highs = np.maximum(opens, closes) + span * rng.uniform(0.2, 1, n)
        lows = np.minimum(opens, closes) - span * rng.uniform(0.2, 1, n)
        base_vol = 1e6 * (1 + abs(hash(symbol)) % 9)
        vols = base_vol * (1 + 3 * np.abs(rets) / max(sigma, 1e-9)) * rng.uniform(0.5, 1.5, n)
        now_bucket = int(time.time() // step * step)
        times = now_bucket - step * np.arange(n - 1, -1, -1)
        return [{"time": int(t), "open": float(o), "high": float(h), "low": float(l), "close": float(c),
                 "volume": float(v)} for t, o, h, l, c, v in zip(times, opens, highs, lows, closes, vols)]

    def candles(self, symbol: str, interval: str, limit: int = 500) -> Candles:
        key = (symbol, interval)
        self.tick(symbol, interval)   # creates the full 1000-bar history on first use
        return Candles(symbol, interval, self.name, False, list(self._live[key]["rows"][-limit:]))

    def tick(self, symbol: str, interval: str) -> dict:
        """Advance the live candle by one random tick; opens a new candle when the interval rolls."""
        key = (symbol, interval)
        if key not in self._live:
            self._live[key] = {"rows": self._history(symbol, interval, 1000)}
        rows = self._live[key]["rows"]
        step = INTERVAL_SECONDS[interval]
        bucket = int(time.time() // step * step)
        last = rows[-1]
        if bucket > last["time"]:
            last = {"time": bucket, "open": last["close"], "high": last["close"], "low": last["close"],
                    "close": last["close"], "volume": 0.0}
            rows.append(last)
            del rows[:-1000]
        price = self.spot(symbol)
        last["close"] = price
        last["high"] = max(last["high"], price)
        last["low"] = min(last["low"], price)
        last["volume"] += abs(np.random.normal(0, 1)) * 1e4
        return dict(last)


# ---------------------------------------------------------------- Router
_binance, _yahoo, _demo = BinanceProvider(), YahooProvider(), DemoProvider()


def mode() -> str:
    return os.environ.get("QUANT_DATA", "auto").lower()   # auto | demo


def get_candles(symbol: str, interval: str = "1d", limit: int = 500, use_cache: bool = True) -> Candles:
    if interval not in INTERVAL_SECONDS:
        raise ValueError(f"interval must be one of {list(INTERVAL_SECONDS)}")
    if mode() == "demo":
        return _demo.candles(symbol, interval, limit)
    ttl = 2 if symbol in CRYPTO else 15
    key = (symbol, interval, limit)
    if use_cache and (hit := _cache.get(key, ttl)):
        return hit
    chain = [_binance, _yahoo] if symbol in CRYPTO else [_yahoo]
    for p in chain:
        try:
            c = p.candles(symbol, interval, limit)
            if c.rows:
                _cache.set(key, c)
                return c
        except Exception:
            continue
    return _demo.candles(symbol, interval, limit)


def fx_to_idr(currency: str) -> float:
    """Rupiah per 1 unit of `currency` (IDR=X / CCY=X)."""
    if currency == "IDR":
        return 1.0
    usd_idr = get_candles("IDR=X", "1d", limit=5).rows[-1]["close"]
    if currency == "USD":
        return usd_idr
    usd_ccy = get_candles(f"{currency}=X", "1d", limit=5).rows[-1]["close"]
    return usd_idr / usd_ccy


def last_price(symbol: str) -> float:
    iv = "1m" if symbol in CRYPTO else "1d"
    return get_candles(symbol, iv, limit=5).rows[-1]["close"]


def poll_seconds(source: str) -> float:
    return {"binance": 2.0, "yahoo": 15.0, "demo": 1.0}.get(source, 5.0)


def latest(symbol: str, interval: str, source: str) -> list[dict]:
    """Newest candle(s) for the live stream."""
    if source == "demo":
        return [_demo.tick(symbol, interval)]
    c = get_candles(symbol, interval, limit=3, use_cache=False)
    return c.rows[-2:]
