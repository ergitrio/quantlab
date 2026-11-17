"""Vectorised backtester. No look-ahead: position decided at close t is applied to return t+1."""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
from .metrics import summarize

@dataclass
class Result:
    returns: pd.Series
    equity: pd.Series
    position: pd.Series
    stats: dict
    n_trades: int

def backtest(prices: pd.Series, position: pd.Series, fee: float = 0.001, slippage: float = 0.0005) -> Result:
    """fee+slippage are charged per unit of position change (default 0.15% per side)."""
    position = position.reindex(prices.index).fillna(0.0)
    applied = position.shift(1).fillna(0.0)          # <- the anti-look-ahead shift
    gross = prices.pct_change().fillna(0.0) * applied
    turnover = applied.diff().abs().fillna(applied.abs())
    net = gross - turnover * (fee + slippage)
    equity = (1 + net).cumprod()
    return Result(net, equity, applied, summarize(net), int((turnover > 0).sum()))
