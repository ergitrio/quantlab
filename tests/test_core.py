import numpy as np, pandas as pd, pytest
from quantlab import data, strategies as S
from quantlab.backtest import backtest
from quantlab.metrics import max_drawdown, summarize
from quantlab.montecarlo import bootstrap_paths, required_to_reach
from quantlab.paper import PaperAccount

def test_no_lookahead():
    # Signal peeks at TODAY's close-to-close return. Executed same day it would be a money machine;
    # the backtester must delay it one bar, so it should earn ~nothing (random walk).
    p = data.synthetic_prices(3000, mu=0.0, seed=1)
    peek = (p.pct_change() > 0).astype(float)
    r = backtest(p, peek, fee=0, slippage=0)
    cheat = (p.pct_change().clip(lower=0)).sum()
    assert cheat > 5 * abs(r.returns.sum())   # cheating would earn >5x what we got
    assert r.stats["sharpe"] < 1.0

def test_zero_fee_buyhold_matches_price():
    p = data.synthetic_prices(300, seed=2)
    r = backtest(p, S.buy_and_hold(p), fee=0, slippage=0)
    assert r.equity.iloc[-1] == pytest.approx(p.iloc[-1] / p.iloc[0], rel=1e-9)

def test_fees_reduce_returns():
    p = data.synthetic_prices(500, seed=3)
    pos = S.sma_crossover(p, 5, 20)
    assert backtest(p, pos, fee=0.01).equity.iloc[-1] < backtest(p, pos, fee=0).equity.iloc[-1]

def test_max_drawdown():
    assert max_drawdown(pd.Series([1, 2, 1, 3])) == pytest.approx(-0.5)

def test_montecarlo_shape_and_positive():
    r = backtest(data.synthetic_prices(500, seed=4), S.buy_and_hold(data.synthetic_prices(500, seed=4))).returns
    f = bootstrap_paths(r, horizon=100, n_paths=200)
    assert f.shape == (200,) and (f > 0).all()

def test_goal_zero_start_needs_savings():
    assert required_to_reach(0, 1e9, 0.08, 10) > 0

def test_paper_account_rules(tmp_path):
    a = PaperAccount(cash=1000, fee=0)
    a.buy("X", 10, 50)
    with pytest.raises(ValueError): a.buy("X", 10, 100)
    with pytest.raises(ValueError): a.sell("X", 10, 60)
    a.sell("X", 12, 50); assert a.cash == 1100 and a.realized_pnl == 100 and a.win_rate() == 1.0
    a.save(tmp_path / "a.json"); assert PaperAccount.load(tmp_path / "a.json").cash == 1100

def test_fast_slow_validation():
    with pytest.raises(ValueError): S.sma_crossover(data.synthetic_prices(200), 50, 20)
