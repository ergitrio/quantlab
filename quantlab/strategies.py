"""Strategies return a position series in {0,1} (long/flat), decided using data up to t."""
from __future__ import annotations
import pandas as pd

def buy_and_hold(prices: pd.Series) -> pd.Series:
    return pd.Series(1.0, index=prices.index)

def sma_crossover(prices: pd.Series, fast: int = 20, slow: int = 100) -> pd.Series:
    if fast >= slow:
        raise ValueError("fast must be < slow")
    f, s = prices.rolling(fast).mean(), prices.rolling(slow).mean()
    return (f > s).astype(float).where(s.notna(), 0.0)

def momentum(prices: pd.Series, lookback: int = 120) -> pd.Series:
    return (prices.pct_change(lookback) > 0).astype(float).where(prices.shift(lookback).notna(), 0.0)

def rsi_mean_reversion(prices: pd.Series, period: int = 14, low: float = 30, high: float = 55) -> pd.Series:
    d = prices.diff()
    up = d.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, 1e-12))
    pos, cur = [], 0.0
    for v in rsi:
        if v != v: cur = 0.0
        elif v < low: cur = 1.0
        elif v > high: cur = 0.0
        pos.append(cur)
    return pd.Series(pos, index=prices.index)

STRATEGIES = {"buy_hold": buy_and_hold, "sma": sma_crossover,
              "momentum": momentum, "rsi": rsi_mean_reversion}
