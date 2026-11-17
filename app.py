"""Quant Desk — platform latihan investasi (uang virtual). Jalankan: streamlit run app.py"""
from __future__ import annotations
import pandas as pd
import streamlit as st

from quantlab import data, strategies as S
from quantlab.backtest import backtest
from quantlab.metrics import summarize
from quantlab.montecarlo import bootstrap_paths, risk_report, required_to_reach
from quantlab.overfit import train_test_check
from quantlab.paper import PaperAccount
from quantlab.portfolio import WEIGHTERS, backtest_portfolio
from quantlab.risk import drawdown_breaker, var_cvar
from quantlab.signals import signal_report

st.set_page_config(page_title="Quant Desk", page_icon="📈", layout="wide")
ACCOUNT_FILE = "paper_account.json"
rp = lambda x: f"Rp {x:,.0f}".replace(",", ".")
rpj = lambda x: f"Rp {x / 1e6:,.2f} jt".replace(",", "X").replace(".", ",").replace("X", ".")
pct = lambda x: f"{x * 100:.1f}%"

# ---------------- Sidebar: data & mode ----------------
st.sidebar.title("📈 Quant Desk")
st.sidebar.caption("Latihan dengan uang virtual. Bukan saran keuangan.")
source = st.sidebar.radio("Sumber data", ["Sintetis (offline)", "Yahoo Finance"])
if source == "Yahoo Finance":
    raw = st.sidebar.text_input("Ticker (pisahkan koma)", "BBCA.JK,BBRI.JK,TLKM.JK,ASII.JK,BTC-USD")
    tickers = [t.strip() for t in raw.split(",") if t.strip()]
else:
    tickers = None
    seed = st.sidebar.number_input("Seed pasar sintetis", 0, 9999, 7)


@st.cache_data(show_spinner="Mengambil data...")
def get_universe(tickers, seed):
    if tickers:
        return data.load_yfinance_many(tickers)
    return data.synthetic_universe(seed=seed)


try:
    U_full = get_universe(tuple(tickers) if tickers else None, None if tickers else int(seed))
except Exception as e:
    st.error(f"Gagal mengambil data: {e}. Pakai mode sintetis dulu.")
    st.stop()

mode = st.sidebar.radio("Mode", ["🎮 Replay (latihan)", "📡 Live (data terbaru)"],
                        help="Replay menyembunyikan masa depan. Kamu maju hari demi hari, "
                             "mengambil keputusan tanpa tahu hasilnya — seperti trading sungguhan.")

ss = st.session_state
if "acct" not in ss:
    ss.acct = PaperAccount.load(ACCOUNT_FILE)
if "cursor" not in ss or ss.cursor >= len(U_full):
    ss.cursor = 300   # mulai dengan 300 hari riwayat

if mode.startswith("🎮"):
    st.sidebar.caption("Majukan waktu (hari bursa):")
    c1, c2, c3 = st.sidebar.columns(3)
    if c1.button("+1", width="stretch"): ss.cursor = min(ss.cursor + 1, len(U_full) - 1)
    if c2.button("+5", width="stretch"): ss.cursor = min(ss.cursor + 5, len(U_full) - 1)
    if c3.button("+20", width="stretch"): ss.cursor = min(ss.cursor + 20, len(U_full) - 1)
    if st.sidebar.button("↺ Ulang replay dari awal"):
        ss.cursor = 300
    U = U_full.iloc[: ss.cursor + 1]
else:
    U = U_full
today = U.index[-1]
last = U.iloc[-1].to_dict()
st.sidebar.markdown(f"**Tanggal pasar:** {today.date()}")

acct: PaperAccount = ss.acct
equity_now = acct.value(last)
st.sidebar.metric("Nilai akun virtual", rp(equity_now), f"{(equity_now / 10_000_000 - 1) * 100:+.2f}% dari modal awal")
if st.sidebar.button("🗑️ Reset akun ke Rp 10 juta"):
    ss.acct = PaperAccount(); ss.acct.save(ACCOUNT_FILE); st.rerun()

tabs = st.tabs(["🧭 Sinyal", "💼 Trading", "🔬 Backtest", "🧺 Portofolio", "🎲 Risiko", "🎯 Target"])

# ---------------- Tab 1: Signal desk ----------------
with tabs[0]:
    sym = st.selectbox("Aset", list(U.columns), key="sig_sym")
    p = U[sym]
    rep = signal_report(p, equity=max(equity_now, 1))
    a, b, c, d = st.columns(4)
    a.metric("Harga", f"{rep['price']:,.2f}")
    b.metric("Konsensus 3 strategi", rep["action"], f"skor {rep['score']:.2f}", delta_color="off", delta_arrow="off")
    c.metric("Rezim volatilitas", rep["regime"], "vol " + pct(rep["vol_annual_now"]) + "/th", delta_color="off", delta_arrow="off")
    d.metric("VaR 95% 1-hari", pct(rep["var95_1d"]))
    st.line_chart(pd.DataFrame({"harga": p, "SMA20": p.rolling(20).mean(), "SMA100": p.rolling(100).mean()}).iloc[-250:])
    st.markdown("**Suara tiap strategi:** " + " · ".join(
        f"{n.upper()} {'🟢 pegang' if v else '⚪ keluar'}" for n, v in rep["votes"].items()))
    st.info(
        f"Jika kamu masuk: stop-loss di **{rep['stop']:,.2f}**, ukuran maksimal "
        f"**{rep['suggested_shares']:,} unit** (risiko 1% akun = {rp(rep['max_loss_if_stopped'])}, "
        f"dibatasi 25% akun per posisi)."
    )
    st.warning(
        f"Konteks jujur: Sharpe historis SMA di aset ini = **{rep['sma_hist_sharpe']:.2f}**. "
        "Sinyal ini aturan mekanis, bukan ramalan. Sebelum percaya, uji di tab Backtest → Uji Overfitting."
    )

# ---------------- Tab 2: Paper trading ----------------
with tabs[1]:
    if drawdown_breaker(pd.Series([10_000_000] + [v for _, v in acct.equity_history] + [equity_now]), -0.20):
        st.error("⛔ Circuit breaker: akun turun >20% dari puncak. Quant profesional berhenti dan mengevaluasi di titik ini.")
    left, right = st.columns([1, 1])
    with left:
        st.subheader("Order")
        osym = st.selectbox("Aset", list(U.columns), key="ord_sym")
        price = float(last[osym])
        st.write(f"Harga eksekusi: **{price:,.2f}** (fee {acct.fee * 100:.2f}%)")
        qty = st.number_input("Jumlah unit", min_value=0.0, value=0.0, step=1.0)
        reason = st.text_input("Alasan (wajib — ini jurnal tradingmu)", placeholder="mis. 3/3 strategi beli, rezim tenang")
        cb, cs = st.columns(2)
        for btn, side in ((cb, "BELI"), (cs, "JUAL")):
            if btn.button(side, width="stretch"):
                if not reason.strip():
                    st.error("Tulis alasanmu dulu. Trader tanpa jurnal tidak bisa belajar dari kesalahan.")
                else:
                    try:
                        (acct.buy if side == "BELI" else acct.sell)(osym, price, qty, reason)
                        acct.mark(last); acct.save(ACCOUNT_FILE)
                        st.success(f"{side} {qty:g} {osym} @ {price:,.2f}"); st.rerun()
                    except ValueError as e:
                        st.error(str(e))
    with right:
        st.subheader("Posisi")
        rows = [{"aset": s, "unit": q, "harga rata2": acct.avg_cost.get(s, 0), "harga kini": last[s],
                 "nilai": q * last[s], "untung/rugi": q * (last[s] - acct.avg_cost.get(s, 0))}
                for s, q in acct.holdings.items()]
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        else:
            st.caption("Belum ada posisi.")
        m1, m2, m3 = st.columns(3)
        m1.metric("Kas", rpj(acct.cash))
        m2.metric("Laba terealisasi", rpj(acct.realized_pnl))
        m3.metric("Win rate", pct(acct.win_rate()))
    st.subheader("📒 Jurnal trading")
    if acct.log:
        st.dataframe(pd.DataFrame(acct.log[::-1]), hide_index=True, width="stretch")
    else:
        st.caption("Belum ada transaksi. Setiap order akan tercatat di sini beserta alasannya.")
    if len(acct.equity_history) > 1:
        st.line_chart(pd.DataFrame(acct.equity_history, columns=["waktu", "nilai"]).set_index("waktu"))

# ---------------- Tab 3: Backtest ----------------
with tabs[2]:
    bsym = st.selectbox("Aset", list(U.columns), key="bt_sym")
    fee = st.slider("Fee + slippage per transaksi (%)", 0.0, 1.0, 0.15, 0.05) / 100
    p = U[bsym]
    eq, rows = {}, []
    for name, fn in S.STRATEGIES.items():
        r = backtest(p, fn(p), fee=fee, slippage=0)
        eq[name] = r.equity
        s = r.stats
        rows.append({"strategi": name, "CAGR": pct(s["cagr"]), "Volatilitas": pct(s["volatility"]),
                     "Sharpe": round(s["sharpe"], 2), "Max drawdown": pct(s["max_drawdown"]), "Transaksi": r.n_trades})
    st.line_chart(pd.DataFrame(eq))
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.subheader("Uji Overfitting (data latih 60% → data uji 40%)")
    which = st.radio("Strategi", ["sma", "momentum"], horizontal=True)
    grids = {"sma": (S.sma_crossover, {"fast": [5, 10, 20, 30, 50], "slow": [50, 100, 150, 200]}),
             "momentum": (S.momentum, {"lookback": [20, 60, 90, 120, 180, 250]})}
    fn, grid = grids[which]
    res = train_test_check(p, fn, grid, fee=fee)
    o1, o2, o3 = st.columns(3)
    o1.metric("Parameter terbaik (latih)", str(res["best_params"]))
    o2.metric("Sharpe di data latih", f"{res['train_sharpe']:.2f}")
    o3.metric("Sharpe di data uji", f"{res['test_sharpe']:.2f}", f"{res['test_sharpe'] - res['train_sharpe']:+.2f}")
    st.caption(f"{res['n_trials']} kombinasi dicoba. p-value terkoreksi: {res['train_pvalue_corrected']:.2f} "
               "(di atas 0,05 = hasil bisa jadi cuma hoki).")

# ---------------- Tab 4: Portfolio ----------------
with tabs[3]:
    st.write("Bandingkan cara membagi uang ke banyak aset, rebalance bulanan.")
    pres, prow = {}, []
    if len(U) > 200:
        for name, fn in WEIGHTERS.items():
            r = backtest_portfolio(U, fn)
            pres[name] = r
            s = r["stats"]
            prow.append({"metode": name, "CAGR": pct(s["cagr"]), "Volatilitas": pct(s["volatility"]),
                         "Sharpe": round(s["sharpe"], 2), "Max drawdown": pct(s["max_drawdown"])})
        st.line_chart(pd.DataFrame({k: v["equity"] for k, v in pres.items()}))
        st.dataframe(pd.DataFrame(prow), hide_index=True, width="stretch")
        pick = st.selectbox("Lihat bobot", list(pres))
        st.area_chart(pres[pick]["weights"])
        st.subheader("Korelasi return")
        st.dataframe(U.pct_change().corr().round(2), width="stretch")
        st.caption("Korelasi tinggi = diversifikasi lemah. Saat krisis, korelasi biasanya naik.")
    else:
        st.info("Butuh minimal 200 hari data.")

# ---------------- Tab 5: Risk ----------------
with tabs[4]:
    rsym = st.selectbox("Aset", list(U.columns), key="risk_sym")
    strat = st.selectbox("Strategi", list(S.STRATEGIES), key="risk_strat")
    horizon = st.slider("Horizon (hari bursa)", 20, 756, 252)
    r = backtest(U[rsym], S.STRATEGIES[strat](U[rsym])).returns
    final = bootstrap_paths(r, horizon=horizon, n_paths=3000)
    rr = risk_report(final)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Median hasil", f"{rr['median']:.2f}x")
    k2.metric("Skenario buruk (5%)", f"{rr['p5']:.2f}x")
    k3.metric("Peluang rugi", pct(rr["prob_loss"]))
    k4.metric("Peluang rugi >50%", pct(rr["prob_lose_50pct"]))
    st.bar_chart(pd.Series(final).round(2).value_counts().sort_index())
    v, cv = var_cvar(r[r != 0] if (r != 0).sum() > 30 else r)
    st.caption(f"VaR 95%: pada 1 dari 20 hari, rugi ≥ {pct(v)}. CVaR (rata-rata hari terburuk): {pct(cv)}.")

# ---------------- Tab 6: Goal ----------------
with tabs[5]:
    g1, g2 = st.columns(2)
    target = g1.number_input("Target (Rp)", value=1_000_000_000, step=50_000_000)
    initial = g1.number_input("Modal awal (Rp)", value=0, step=1_000_000)
    yrs = g2.slider("Jangka waktu (tahun)", 1, 40, 10)
    ar = g2.slider("Asumsi return per tahun (%)", 0.0, 20.0, 8.0, 0.5) / 100
    need = required_to_reach(initial, target, ar, yrs)
    st.metric("Perlu disisihkan per bulan", rp(need))
    sens = pd.DataFrame({f"{x}%/th": [required_to_reach(initial, target, x / 100, y) for y in (5, 10, 15, 20, 25)]
                         for x in (4, 8, 12)}, index=[f"{y} th" for y in (5, 10, 15, 20, 25)])
    st.dataframe(sens.map(rp), width="stretch")
    st.caption("Waktu dan setoran rutin jauh lebih menentukan daripada strategi trading. Return di atas 12%/th "
               "konsisten selama puluhan tahun sangat jarang, bahkan untuk profesional.")
