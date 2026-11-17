"""Monte Carlo: bootstrap trade returns to see the RANGE of outcomes, incl. ruin probability."""
from __future__ import annotations
import numpy as np
import pandas as pd

def bootstrap_paths(returns: pd.Series, horizon: int = 252, n_paths: int = 5000,
                    block: int = 10, seed: int | None = 0) -> np.ndarray:
    """Block bootstrap (keeps short-term autocorrelation). Returns final-equity multiples per path."""
    r = returns.dropna().to_numpy()
    if len(r) < block:
        raise ValueError("not enough data")
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(horizon / block))
    starts = rng.integers(0, len(r) - block + 1, size=(n_paths, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)).reshape(n_paths, -1)[:, :horizon]
    return np.prod(1 + r[idx], axis=1)

def risk_report(final: np.ndarray, ruin_level: float = 0.5) -> dict:
    return {"median": float(np.median(final)), "p5": float(np.percentile(final, 5)),
            "p95": float(np.percentile(final, 95)),
            "prob_loss": float((final < 1).mean()),
            f"prob_lose_{int((1-ruin_level)*100)}pct": float((final < ruin_level).mean())}

def required_to_reach(initial: float, target: float, annual_return: float, years: float) -> float:
    """Monthly contribution needed to hit `target` (future-value of annuity). Shows 0 start needs saving."""
    m, r = int(years * 12), (1 + annual_return) ** (1 / 12) - 1
    growth = initial * (1 + r) ** m
    fv_factor = m if r == 0 else ((1 + r) ** m - 1) / r
    return max(0.0, (target - growth) / fv_factor)
