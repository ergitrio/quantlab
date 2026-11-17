"""CLI: python -m quantlab.cli --help"""
from __future__ import annotations
import argparse
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from . import data, strategies as S
from .backtest import backtest
from .montecarlo import bootstrap_paths, risk_report, required_to_reach
from .overfit import train_test_check
from .metrics import sharpe_tstat_pvalue

def get_prices(a):
    if a.csv: return data.load_csv(a.csv)
    if a.ticker: return data.load_yfinance(a.ticker, a.start)
    return data.synthetic_prices(seed=a.seed)

def pct(x): return f"{x*100:6.1f}%"

def cmd_backtest(a):
    p = get_prices(a)
    print(f"Data: {len(p)} hari ({p.index[0].date()} -> {p.index[-1].date()})\n")
    fig, ax = plt.subplots(figsize=(10, 5))
    print(f"{'strategi':10} {'CAGR':>8} {'Vol':>8} {'Sharpe':>7} {'MaxDD':>8} {'Trades':>7}")
    for name, fn in S.STRATEGIES.items():
        r = backtest(p, fn(p), fee=a.fee)
        s = r.stats
        print(f"{name:10} {pct(s['cagr']):>8} {pct(s['volatility']):>8} {s['sharpe']:7.2f} {pct(s['max_drawdown']):>8} {r.n_trades:7d}")
        r.equity.plot(ax=ax, label=name)
    ax.set_title("Equity curve (net of fees)"); ax.legend(); ax.grid(alpha=.3)
    fig.savefig(a.out, dpi=120, bbox_inches="tight"); print(f"\nGrafik: {a.out}")

def cmd_montecarlo(a):
    p = get_prices(a)
    r = backtest(p, S.STRATEGIES[a.strategy](p), fee=a.fee)
    rep = risk_report(bootstrap_paths(r.returns, horizon=a.horizon, seed=a.seed))
    print(f"Strategi {a.strategy}, horizon {a.horizon} hari, 5000 simulasi:")
    for k, v in rep.items(): print(f"  {k:18} {v:.3f}")

def cmd_overfit(a):
    p = get_prices(a)
    grids = {"sma": (S.sma_crossover, {"fast": [5, 10, 20, 30, 50], "slow": [50, 100, 150, 200]}),
             "momentum": (S.momentum, {"lookback": [20, 60, 90, 120, 180, 250]})}
    fn, grid = grids[a.strategy]
    res = train_test_check(p, fn, grid, fee=a.fee)
    print(f"Param terbaik di data latih: {res['best_params']} ({res['n_trials']} percobaan)")
    print(f"Sharpe latih : {res['train_sharpe']:.2f}   (p-value terkoreksi: {res['train_pvalue_corrected']:.2f})")
    print(f"Sharpe uji   : {res['test_sharpe']:.2f}   <- data yang belum pernah dilihat")
    print("Jika Sharpe uji jauh lebih kecil dari latih = overfitting.")

def cmd_goal(a):
    m = required_to_reach(a.initial, a.target, a.annual_return, a.years)
    print(f"Target Rp {a.target:,.0f} dalam {a.years} th @ {a.annual_return*100:.0f}%/th dari modal Rp {a.initial:,.0f}")
    print(f"=> perlu menabung/menginvestasikan Rp {m:,.0f} per bulan")

def main():
    ap = argparse.ArgumentParser(description="Quant Lab (edukasi, bukan saran keuangan)")
    sub = ap.add_subparsers(required=True)
    def common(sp):
        sp.add_argument("--csv"); sp.add_argument("--ticker", help="mis. BBCA.JK atau BTC-USD")
        sp.add_argument("--start", default="2018-01-01"); sp.add_argument("--seed", type=int, default=42)
        sp.add_argument("--fee", type=float, default=0.001)
    b = sub.add_parser("backtest"); common(b); b.add_argument("--out", default="equity.png"); b.set_defaults(f=cmd_backtest)
    m = sub.add_parser("montecarlo"); common(m); m.add_argument("--strategy", default="sma", choices=list(S.STRATEGIES))
    m.add_argument("--horizon", type=int, default=252); m.set_defaults(f=cmd_montecarlo)
    o = sub.add_parser("overfit"); common(o); o.add_argument("--strategy", default="sma", choices=["sma", "momentum"]); o.set_defaults(f=cmd_overfit)
    g = sub.add_parser("goal"); g.add_argument("--target", type=float, default=1e9)
    g.add_argument("--initial", type=float, default=0); g.add_argument("--annual-return", type=float, default=0.08)
    g.add_argument("--years", type=float, default=10); g.set_defaults(f=cmd_goal)
    a = ap.parse_args(); a.f(a)

if __name__ == "__main__":
    main()
