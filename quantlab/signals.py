"""Daily signal desk: what each rule says *today*, plus honest context."""
from __future__ import annotations
import pandas as pd
from . import strategies as S
from .backtest import backtest
from .risk import atr_stop, kelly_fraction, var_cvar


def signal_report(prices: pd.Series, equity: float = 10_000_000, risk_pct: float = 0.01) -> dict:
    votes = {n: int(f(prices).iloc[-1]) for n, f in S.STRATEGIES.items() if n != "buy_hold"}
    score = sum(votes.values()) / len(votes)
    rets = prices.pct_change().dropna()
    vol_now = rets.iloc[-20:].std() * 252 ** 0.5
    vol_long = rets.std() * 252 ** 0.5
    stop = atr_stop(prices)
    price = float(prices.iloc[-1])
    shares = int((equity * risk_pct) // (price - stop)) if price > stop else 0
    # cap so one position never exceeds 25% of equity
    shares = min(shares, int(0.25 * equity // price))
    bt = backtest(prices, S.sma_crossover(prices))
    var95, cvar95 = var_cvar(rets)
    return {
        "price": price, "votes": votes, "score": score,
        "action": "BELI/TAHAN" if score >= 2 / 3 else ("JUAL/TUNGGU" if score <= 1 / 3 else "NETRAL"),
        "regime": "volatil" if vol_now > 1.3 * vol_long else ("tenang" if vol_now < 0.8 * vol_long else "normal"),
        "vol_annual_now": float(vol_now), "stop": stop, "suggested_shares": shares,
        "max_loss_if_stopped": shares * (price - stop),
        "var95_1d": var95, "cvar95_1d": cvar95,
        "half_kelly_buyhold": kelly_fraction(rets),
        "sma_hist_sharpe": bt.stats["sharpe"],
    }
