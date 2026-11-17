"""Technical + statistical analysis on OHLCV, shared by the API and the AI agent."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from quantlab import strategies as S
from quantlab.backtest import backtest
from quantlab.montecarlo import bootstrap_paths, risk_report
from quantlab.risk import var_cvar

from .markets import NAMES, currency_of, group_of
from .providers import fx_to_idr, get_candles

PERIODS = {"1m": 525600, "5m": 105120, "15m": 35040, "1h": 8760, "4h": 2190, "1d": 252, "1w": 52}


def _clean(x):
    if isinstance(x, (float, np.floating)):
        return None if (math.isnan(x) or math.isinf(x)) else round(float(x), 6)
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def macd(close: pd.Series):
    m = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    sig = m.ewm(span=9, adjust=False).mean()
    return m, sig, m - sig


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def indicator_series(df: pd.DataFrame) -> dict:
    """Series for the chart overlays/panes, as [{time, value}] lists."""
    c = df["close"]
    m, s, h = macd(c)
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()

    def pts(series):
        return [{"time": int(t), "value": float(v)} for t, v in zip(df["time"], series) if pd.notna(v)]

    return {"sma20": pts(c.rolling(20).mean()), "sma50": pts(c.rolling(50).mean()),
            "ema200": pts(c.ewm(span=200, adjust=False).mean().where(np.arange(len(c)) >= 199)),
            "bb_upper": pts(mid + 2 * sd), "bb_lower": pts(mid - 2 * sd),
            "rsi": pts(rsi(c)), "macd": pts(m), "macd_signal": pts(s), "macd_hist": pts(h)}


def support_resistance(df: pd.DataFrame, window: int = 5, n: int = 3) -> dict:
    """Recent swing lows/highs closest to the current price."""
    hi, lo, price = df["high"], df["low"], float(df["close"].iloc[-1])
    piv_hi = hi[(hi == hi.rolling(2 * window + 1, center=True).max())].iloc[-60:]
    piv_lo = lo[(lo == lo.rolling(2 * window + 1, center=True).min())].iloc[-60:]
    res = sorted({round(float(v), 6) for v in piv_hi if v > price})[:n]
    sup = sorted({round(float(v), 6) for v in piv_lo if v < price}, reverse=True)[:n]
    return {"support": sup, "resistance": res}


def technical_analysis(symbol: str, interval: str = "1d") -> dict:
    c = get_candles(symbol, interval)
    df = c.to_frame()
    if len(df) < 60:
        return {"symbol": symbol, "error": "data terlalu sedikit untuk analisis"}
    close = df["close"]
    price = float(close.iloc[-1])
    sma20, sma50 = close.rolling(20).mean().iloc[-1], close.rolling(50).mean().iloc[-1]
    ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1] if len(df) >= 200 else np.nan
    r = float(rsi(close).iloc[-1])
    m, sgl, hist = macd(close)
    a = float(atr(df).iloc[-1])
    rets = close.pct_change().dropna()
    ppy = PERIODS[interval]
    vol_now, vol_long = rets.iloc[-20:].std() * math.sqrt(ppy), rets.std() * math.sqrt(ppy)
    var95, cvar95 = var_cvar(rets)

    checks = {
        "harga > SMA20": price > sma20,
        "SMA20 > SMA50": sma20 > sma50,
        "harga > EMA200": bool(price > ema200) if not np.isnan(ema200) else None,
        "MACD > signal": bool(m.iloc[-1] > sgl.iloc[-1]),
        "RSI 45-70 (momentum sehat)": 45 <= r <= 70,
    }
    valid = [v for v in checks.values() if v is not None]
    score = sum(valid) / len(valid)
    bias = "BULLISH" if score >= 0.7 else "BEARISH" if score <= 0.3 else "NETRAL"
    perf = {lbl: float(close.iloc[-1] / close.iloc[-k - 1] - 1) for lbl, k in
            (("1 bar", 1), ("20 bar", 20), ("60 bar", 60)) if len(close) > k}

    return _clean({
        "symbol": symbol, "name": NAMES.get(symbol, symbol), "market": group_of(symbol),
        "currency": currency_of(symbol),
        "interval": interval, "source": c.source, "delayed": c.delayed,
        "last_time": int(df["time"].iloc[-1]), "price": price,
        "change": perf, "bias": bias, "bias_score": score, "checks": checks,
        "indicators": {"sma20": sma20, "sma50": sma50, "ema200": ema200, "rsi14": r,
                       "macd": float(m.iloc[-1]), "macd_signal": float(sgl.iloc[-1]), "atr14": a,
                       "bb_upper": float(close.rolling(20).mean().iloc[-1] + 2 * close.rolling(20).std().iloc[-1]),
                       "bb_lower": float(close.rolling(20).mean().iloc[-1] - 2 * close.rolling(20).std().iloc[-1])},
        "levels": support_resistance(df),
        "risk": {"vol_annual_now": vol_now, "vol_annual_avg": vol_long,
                 "regime": "volatil" if vol_now > 1.3 * vol_long else "tenang" if vol_now < 0.8 * vol_long else "normal",
                 "var95_per_bar": var95, "cvar95_per_bar": cvar95,
                 "atr_stop_long": price - 2 * a, "atr_stop_short": price + 2 * a},
    })


def run_backtest(symbol: str, interval: str = "1d", fee: float = 0.0015) -> dict:
    c = get_candles(symbol, interval)
    close = c.to_frame()["close"]
    out = {}
    for name, fn in S.STRATEGIES.items():
        res = backtest(close, fn(close), fee=fee, slippage=0.0005)
        s = res.stats
        n, ppy = s["n_periods"], PERIODS[interval]
        # annualising a few weeks of data gives absurd numbers, so only report CAGR for >= ~1 year
        cagr = float(res.equity.iloc[-1] ** (ppy / n) - 1) if n >= ppy * 0.9 else None
        out[name] = {"total_return": s["total_return"], "cagr": cagr,
                     "sharpe": s["sharpe"] * math.sqrt(ppy / 252), "max_drawdown": s["max_drawdown"],
                     "trades": res.n_trades}
    return _clean({"symbol": symbol, "interval": interval, "bars": len(close), "source": c.source,
                   "fee_per_side": fee, "results": out,
                   "note": "Hasil masa lalu tidak menjamin masa depan. Bandingkan setiap strategi dengan buy_hold."})


def monte_carlo(symbol: str, strategy: str = "buy_hold", horizon_bars: int = 252, interval: str = "1d") -> dict:
    close = get_candles(symbol, interval).to_frame()["close"]
    if strategy not in S.STRATEGIES:
        strategy = "buy_hold"
    r = backtest(close, S.STRATEGIES[strategy](close)).returns
    rep = risk_report(bootstrap_paths(r, horizon=horizon_bars, n_paths=3000, seed=1))
    return _clean({"symbol": symbol, "strategy": strategy, "horizon_bars": horizon_bars,
                   "interval": interval, **rep,
                   "explain": "Nilai = kelipatan modal di akhir horizon (1.0 = impas). p5 = skenario buruk 1 dari 20."})


def market_overview(group: str | None = None) -> dict:
    from .markets import MARKETS
    groups = {group: MARKETS[group]} if group in MARKETS else MARKETS
    out = {}
    for g, items in groups.items():
        rows = []
        for sym, name in items:
            try:
                c = get_candles(sym, "1d", limit=260)
                cl = [x["close"] for x in c.rows]
                rows.append({"symbol": sym, "name": name, "price": cl[-1],
                             "chg_1d": cl[-1] / cl[-2] - 1, "chg_1m": cl[-1] / cl[-22] - 1 if len(cl) > 22 else None,
                             "chg_1y": cl[-1] / cl[0] - 1, "source": c.source})
            except Exception as e:  # keep going for other markets
                rows.append({"symbol": sym, "name": name, "error": str(e)})
        out[g] = rows
    return _clean(out)


def position_size(symbol: str, equity_idr: float, risk_pct: float = 0.01, interval: str = "1d") -> dict:
    """Units to buy so that hitting a 2xATR stop costs `risk_pct` of a Rupiah account. Fractional units allowed."""
    ta = technical_analysis(symbol, interval)
    ccy = ta["currency"]
    fx = fx_to_idr(ccy)
    price, stop = ta["price"], ta["risk"]["atr_stop_long"]
    per_unit_idr = (price - stop) * fx
    units = equity_idr * risk_pct / per_unit_idr if per_unit_idr > 0 else 0.0
    units = min(units, 0.25 * equity_idr / (price * fx))
    units = float(int(units)) if units >= 10 else round(units, 6)
    return _clean({"symbol": symbol, "currency": ccy, "fx_to_idr": fx, "price": price, "stop_loss": stop,
                   "units": units, "position_value_idr": units * price * fx, "max_loss_at_stop_idr": units * per_unit_idr,
                   "rule": f"risiko {risk_pct * 100:.1f}% akun per trade, posisi maks 25% akun, stop = 2×ATR"})
