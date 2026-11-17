"""Risk management: position sizing, VaR/CVaR, drawdown circuit breaker."""
from __future__ import annotations
import numpy as np
import pandas as pd


def fixed_fractional_size(equity: float, price: float, stop_price: float, risk_pct: float = 0.01) -> int:
    """Shares so that hitting the stop loses at most `risk_pct` of equity. (The 1% rule.)"""
    per_share = price - stop_price
    if per_share <= 0:
        raise ValueError("stop must be below entry price for a long trade")
    return int((equity * risk_pct) // per_share)


def atr_stop(prices: pd.Series, mult: float = 2.0, period: int = 14) -> float:
    """Close-only ATR approximation: stop = last price - mult * avg absolute daily move."""
    atr = prices.diff().abs().rolling(period).mean().iloc[-1]
    return float(prices.iloc[-1] - mult * atr)


def kelly_fraction(returns: pd.Series, cap: float = 0.25, shrink: float = 0.5) -> float:
    """Continuous Kelly mu/sigma^2, halved (estimation error!) and capped. 0 if no edge."""
    r = returns.dropna()
    if len(r) < 30 or r.var() == 0:
        return 0.0
    f = r.mean() / r.var()
    return float(np.clip(f * shrink, 0.0, cap))


def var_cvar(returns: pd.Series, level: float = 0.95) -> tuple[float, float]:
    """Historical 1-day VaR & CVaR as positive loss fractions."""
    r = returns.dropna()
    q = np.quantile(r, 1 - level)
    return float(-q), float(-r[r <= q].mean())


def drawdown_breaker(equity: pd.Series, limit: float = -0.20) -> bool:
    """True = stop trading (drawdown from peak beyond limit). Pros have this rule; you should too."""
    dd = equity.iloc[-1] / equity.cummax().iloc[-1] - 1
    return bool(dd <= limit)
