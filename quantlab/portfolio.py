"""Multi-asset portfolio construction & monthly-rebalanced backtest."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .metrics import summarize


def w_equal(hist: pd.DataFrame) -> pd.Series:
    return pd.Series(1 / hist.shape[1], index=hist.columns)


def w_inverse_vol(hist: pd.DataFrame, lookback: int = 60) -> pd.Series:
    vol = hist.pct_change().iloc[-lookback:].std()
    inv = 1 / vol.replace(0, np.nan)
    return (inv / inv.sum()).fillna(0)


def w_min_variance(hist: pd.DataFrame, lookback: int = 120) -> pd.Series:
    """Long-only min-variance via clipped closed form (no optimizer dependency)."""
    cov = np.array(hist.pct_change().iloc[-lookback:].cov(), dtype=float)  # writable copy
    cov += np.eye(len(cov)) * 1e-6
    w = np.linalg.solve(cov, np.ones(len(cov)))
    w = np.clip(w, 0, None)
    w = w / w.sum() if w.sum() > 0 else np.ones(len(w)) / len(w)
    return pd.Series(w, index=hist.columns)


def w_momentum_topk(hist: pd.DataFrame, lookback: int = 120, k: int = 2) -> pd.Series:
    mom = hist.iloc[-1] / hist.iloc[-lookback] - 1
    top = mom[mom > 0].nlargest(k).index
    w = pd.Series(0.0, index=hist.columns)
    if len(top):
        w[top] = 1 / len(top)
    return w   # remainder sits in cash


WEIGHTERS = {"equal": w_equal, "inverse_vol": w_inverse_vol,
             "min_variance": w_min_variance, "momentum_top2": w_momentum_topk}


def backtest_portfolio(prices: pd.DataFrame, weigher, warmup: int = 130,
                       fee: float = 0.0015, rebalance: str = "ME") -> dict:
    rets = prices.pct_change().fillna(0)
    dates = prices.index[warmup:]
    reb = set(pd.Series(dates, index=dates).resample(rebalance).last().dropna())
    w = pd.Series(0.0, index=prices.columns)
    out, weights_log = [], {}
    for d in dates:
        r_day = float((w * rets.loc[d]).sum())
        # drift weights with prices
        grown = w * (1 + rets.loc[d])
        tot = grown.sum() + (1 - w.sum())
        w = grown / tot if tot > 0 else w
        if d in reb:  # decide at close using data up to d, apply from next day
            target = weigher(prices.loc[:d])
            r_day -= float((target - w).abs().sum()) * fee
            w = target
            weights_log[d] = target
        out.append(r_day)
    r = pd.Series(out, index=dates)
    return {"returns": r, "equity": (1 + r).cumprod(), "stats": summarize(r),
            "weights": pd.DataFrame(weights_log).T}
