"""Data loading. Supports CSV, optional yfinance, and synthetic data for offline use."""
from __future__ import annotations
import numpy as np
import pandas as pd


def synthetic_prices(n_days: int = 1500, mu: float = 0.08, sigma: float = 0.25,
                     start: float = 100.0, seed: int | None = 42) -> pd.Series:
    """Geometric Brownian Motion daily close prices (252 trading days/year)."""
    rng = np.random.default_rng(seed)
    dt = 1 / 252
    rets = rng.normal((mu - 0.5 * sigma**2) * dt, sigma * np.sqrt(dt), n_days)
    idx = pd.bdate_range("2020-01-01", periods=n_days)
    return pd.Series(start * np.exp(np.cumsum(rets)), index=idx, name="close")


def load_csv(path: str, date_col: str = "Date", price_col: str = "Close") -> pd.Series:
    df = pd.read_csv(path, parse_dates=[date_col]).sort_values(date_col)
    s = df.set_index(date_col)[price_col].astype(float).dropna()
    s.name = "close"
    return s


def load_yfinance(ticker: str, start: str = "2018-01-01") -> pd.Series:
    """Ticker examples: 'BBCA.JK' (IDX), 'BTC-USD' (crypto). Needs `pip install yfinance`."""
    try:
        import yfinance as yf
    except ImportError as e:
        raise RuntimeError("Install yfinance: pip install yfinance") from e
    df = yf.download(ticker, start=start, auto_adjust=True, progress=False)
    if df.empty:
        raise RuntimeError(f"No data for {ticker}")
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = close.dropna().astype(float)
    close.name = "close"
    return close


def synthetic_universe(names=("BBCA", "BBRI", "TLKM", "ASII", "BTC"), n_days: int = 1500,
                       seed: int | None = 7) -> pd.DataFrame:
    """Correlated multi-asset GBM (one common market factor). Columns = tickers."""
    rng = np.random.default_rng(seed)
    k = len(names)
    mus = rng.uniform(0.02, 0.12, k)
    sigs = rng.uniform(0.18, 0.35, k)
    if "BTC" in names:
        i = list(names).index("BTC"); mus[i], sigs[i] = 0.15, 0.65
    market = rng.normal(0, 1, n_days)
    out = {}
    for j, n in enumerate(names):
        z = 0.6 * market + 0.8 * rng.normal(0, 1, n_days)
        dt = 1 / 252
        r = (mus[j] - 0.5 * sigs[j] ** 2) * dt + sigs[j] * np.sqrt(dt) * z
        out[n] = 1000 * np.exp(np.cumsum(r))
    return pd.DataFrame(out, index=pd.bdate_range("2020-01-01", periods=n_days))


def load_yfinance_many(tickers, start: str = "2018-01-01") -> pd.DataFrame:
    frames = {t: load_yfinance(t, start) for t in tickers}
    return pd.DataFrame(frames).ffill().dropna()
