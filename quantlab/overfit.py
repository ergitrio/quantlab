"""Walk-forward & parameter search honesty checks."""
from __future__ import annotations
import itertools
import pandas as pd
from .backtest import backtest
from .metrics import sharpe_tstat_pvalue, deflated_pvalue

def grid_search(prices, strat, grid: dict, **bt):
    rows = []
    for vals in itertools.product(*grid.values()):
        params = dict(zip(grid.keys(), vals))
        try:
            res = backtest(prices, strat(prices, **params), **bt)
        except ValueError:
            continue
        rows.append({**params, "sharpe": res.stats["sharpe"], "pvalue": sharpe_tstat_pvalue(res.returns)})
    return pd.DataFrame(rows).sort_values("sharpe", ascending=False).reset_index(drop=True)

def train_test_check(prices, strat, grid: dict, split: float = 0.6, **bt) -> dict:
    """Pick best params on the first `split` of data, evaluate on unseen remainder."""
    cut = int(len(prices) * split)
    train, test = prices.iloc[:cut], prices.iloc[cut:]
    table = grid_search(train, strat, grid, **bt)
    best = {k: table.iloc[0][k] for k in grid}
    best = {k: int(v) if float(v).is_integer() else float(v) for k, v in best.items()}
    # evaluate on full series (warm-up for indicators) but score only the test part
    full = backtest(prices, strat(prices, **best), **bt).returns.iloc[cut:]
    from .metrics import summarize
    test_stats = summarize(full)
    return {"best_params": best, "train_sharpe": float(table.iloc[0]["sharpe"]),
            "test_sharpe": test_stats["sharpe"], "n_trials": len(table),
            "train_pvalue_corrected": deflated_pvalue(float(table.iloc[0]["pvalue"]), len(table)),
            "test_stats": test_stats}
