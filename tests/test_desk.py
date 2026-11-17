import numpy as np, pandas as pd, pytest
from quantlab import data
from quantlab.risk import fixed_fractional_size, kelly_fraction, var_cvar, drawdown_breaker
from quantlab.portfolio import WEIGHTERS, backtest_portfolio
from quantlab.signals import signal_report

U = data.synthetic_universe(n_days=600)

def test_fixed_fractional():
    assert fixed_fractional_size(10_000_000, 1000, 950, 0.01) == 2000   # 100k risk / 50
    with pytest.raises(ValueError): fixed_fractional_size(1e6, 100, 110)

def test_kelly_no_edge_is_zero():
    r = pd.Series(np.random.default_rng(0).normal(-0.001, 0.01, 500))
    assert kelly_fraction(r) == 0.0

def test_var_cvar_order():
    v, c = var_cvar(pd.Series(np.random.default_rng(1).normal(0, 0.02, 2000)))
    assert 0 < v <= c

def test_breaker():
    assert drawdown_breaker(pd.Series([1, 1.2, 0.9]), -0.2)
    assert not drawdown_breaker(pd.Series([1, 1.2, 1.1]), -0.2)

@pytest.mark.parametrize("name", list(WEIGHTERS))
def test_weights_valid(name):
    w = WEIGHTERS[name](U.iloc[:200])
    assert (w >= 0).all() and w.sum() <= 1 + 1e-9

def test_portfolio_backtest_runs():
    res = backtest_portfolio(U, WEIGHTERS["inverse_vol"])
    assert len(res["returns"]) == len(U) - 130 and np.isfinite(res["stats"]["sharpe"])

def test_signal_report_caps_position():
    rep = signal_report(U["BBCA"], equity=10_000_000)
    assert rep["suggested_shares"] * rep["price"] <= 0.25 * 10_000_000 + 1
    assert rep["action"] in {"BELI/TAHAN", "JUAL/TUNGGU", "NETRAL"}
