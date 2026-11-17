"""Performance & risk statistics."""
from __future__ import annotations
import numpy as np
import pandas as pd
from scipy import stats

def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    return float(((equity - peak) / peak).min())

def summarize(returns: pd.Series, periods: int = 252, rf: float = 0.0) -> dict:
    r = returns.dropna()
    equity = (1 + r).cumprod()
    n = len(r)
    total = float(equity.iloc[-1] - 1) if n else 0.0
    cagr = float(equity.iloc[-1] ** (periods / n) - 1) if n else 0.0
    vol = float(r.std(ddof=1) * np.sqrt(periods)) if n > 1 else 0.0
    ex = r - rf / periods
    sharpe = float(ex.mean() / r.std(ddof=1) * np.sqrt(periods)) if n > 1 and r.std() > 0 else 0.0
    down = r[r < 0].std(ddof=1)
    sortino = float(ex.mean() / down * np.sqrt(periods)) if down and not np.isnan(down) else 0.0
    mdd = max_drawdown(equity) if n else 0.0
    return {"total_return": total, "cagr": cagr, "volatility": vol,
            "sharpe": sharpe, "sortino": sortino, "max_drawdown": mdd,
            "calmar": float(cagr / abs(mdd)) if mdd else 0.0,
            "win_rate": float((r > 0).mean()) if n else 0.0, "n_periods": n}

def sharpe_tstat_pvalue(returns: pd.Series) -> float:
    """One-sided p-value: is mean daily return > 0? Low p = unlikely to be luck (for ONE test only)."""
    r = returns.dropna()
    if len(r) < 3 or r.std() == 0:
        return 1.0
    t, p = stats.ttest_1samp(r, 0.0)
    return float(p / 2 if t > 0 else 1 - p / 2)

def deflated_pvalue(p: float, n_trials: int) -> float:
    """Bonferroni-style correction: trying many strategies inflates false positives."""
    return float(min(1.0, p * max(1, n_trials)))
