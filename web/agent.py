"""AI market-analysis agent.

With ANTHROPIC_API_KEY set, Claude runs a tool-use loop over the Quant Lab analysis functions and
streams its answer. Without a key, a rule-based analyst produces a structured summary so the
panel still works offline.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator

from . import analysis as A
from .markets import MARKETS, NAMES

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
MAX_STEPS = 8

SYMBOL_LIST = "; ".join(f"{g}: " + ", ".join(f"{s} ({n})" for s, n in items) for g, items in MARKETS.items())

SYSTEM = f"""Kamu adalah AI analis pasar di dalam Quant Desk, platform LATIHAN investasi dengan uang virtual milik
seorang mahasiswa Indonesia. Jawab dalam Bahasa Indonesia yang jelas, ringkas, pakai markdown (judul kecil, poin).

Aturan kerja:
- Semua angka (harga, indikator, statistik) WAJIB dari tool. Jangan pernah mengarang harga atau berita.
- Sebutkan sumber data dari hasil tool: "demo" = data sintetis untuk latihan (bukan harga asli),
  "yahoo" = biasanya tertunda 15-20 menit, "binance" = real-time.
- Struktur analisis: tren & momentum → level support/resistance → risiko (volatilitas, VaR, stop ATR) →
  dua skenario (naik/turun) beserta titik invalidasinya → saran latihan (ukuran posisi dengan aturan risiko 1%).
- Bicara dalam probabilitas, bukan kepastian. Tidak ada yang bisa memprediksi harga dengan pasti.
- Jika diminta "pasti untung", "cepat kaya", atau sinyal tanpa risiko: jelaskan dengan jujur kenapa itu tidak ada,
  lalu tawarkan analisis yang realistis.
- Kamu tidak punya akses berita atau data fundamental; katakan itu jika ditanya.
- Ingatkan bahwa ini latihan dan bukan nasihat keuangan cukup SEKALI, singkat, di akhir — jangan berulang.

Simbol yang tersedia (ticker Yahoo): {SYMBOL_LIST}. Simbol Yahoo lain yang valid juga boleh dicoba."""

TOOLS = [
    {"name": "get_market_overview",
     "description": "Harga terakhir dan perubahan 1 hari / 1 bulan / 1 tahun untuk pasar dunia. "
                    "Opsional filter satu grup.",
     "input_schema": {"type": "object", "properties": {
         "group": {"type": "string", "enum": list(MARKETS), "description": "Kosongkan untuk semua pasar."}}}},
    {"name": "get_technical_analysis",
     "description": "Analisis teknikal lengkap satu aset: harga, bias, SMA/EMA, RSI, MACD, Bollinger, ATR, "
                    "support/resistance, rezim volatilitas, VaR.",
     "input_schema": {"type": "object", "required": ["symbol"], "properties": {
         "symbol": {"type": "string"},
         "interval": {"type": "string", "enum": ["15m", "1h", "4h", "1d", "1w"], "default": "1d"}}}},
    {"name": "run_backtest",
     "description": "Backtest 4 strategi (buy_hold, sma, momentum, rsi) pada aset, setelah biaya transaksi.",
     "input_schema": {"type": "object", "required": ["symbol"], "properties": {
         "symbol": {"type": "string"},
         "interval": {"type": "string", "enum": ["1h", "4h", "1d", "1w"], "default": "1d"}}}},
    {"name": "monte_carlo_risk",
     "description": "Simulasi Monte Carlo 3000 jalur: median, skenario buruk 5%, peluang rugi.",
     "input_schema": {"type": "object", "required": ["symbol"], "properties": {
         "symbol": {"type": "string"},
         "strategy": {"type": "string", "enum": ["buy_hold", "sma", "momentum", "rsi"], "default": "buy_hold"},
         "horizon_bars": {"type": "integer", "default": 252}}}},
    {"name": "position_size",
     "description": "Ukuran posisi berdasarkan aturan risiko (stop 2×ATR, risiko % akun, maks 25% akun). "
                    "equity dalam Rupiah; harga aset dikonversi ke Rupiah otomatis.",
     "input_schema": {"type": "object", "required": ["symbol", "equity"], "properties": {
         "symbol": {"type": "string"}, "equity": {"type": "number"},
         "risk_pct": {"type": "number", "default": 0.01}}}},
    {"name": "get_paper_account",
     "description": "Isi akun latihan pengguna: kas, posisi, untung/rugi, jurnal trading terakhir.",
     "input_schema": {"type": "object", "properties": {}}},
]


def run_tool(name: str, args: dict, account_fn=None) -> dict:
    try:
        if name == "get_market_overview":
            return A.market_overview(args.get("group"))
        if name == "get_technical_analysis":
            return A.technical_analysis(args["symbol"], args.get("interval", "1d"))
        if name == "run_backtest":
            return A.run_backtest(args["symbol"], args.get("interval", "1d"))
        if name == "monte_carlo_risk":
            return A.monte_carlo(args["symbol"], args.get("strategy", "buy_hold"), int(args.get("horizon_bars", 252)))
        if name == "position_size":
            return A.position_size(args["symbol"], float(args["equity"]), float(args.get("risk_pct", 0.01)))
        if name == "get_paper_account":
            return account_fn() if account_fn else {"error": "akun tidak tersedia"}
        return {"error": f"tool tidak dikenal: {name}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def _context_note(ctx: dict) -> str:
    sym, iv = ctx.get("symbol"), ctx.get("interval")
    return f"\n\n[Konteks layar pengguna: sedang melihat {sym} ({NAMES.get(sym, sym)}) interval {iv}.]" if sym else ""


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def chat(history: list[dict], ctx: dict, account_fn=None, client=None) -> Iterator[dict]:
    """Yields events: {"type": "text", "text"}, {"type": "tool", "name", "input"}, {"type": "done"}."""
    if client is None and not has_api_key():
        yield from offline_analyst(history, ctx)
        return
    if client is None:
        import anthropic
        client = anthropic.Anthropic()

    messages = [{"role": m["role"], "content": m["content"]} for m in history if m.get("content")]
    if messages and messages[-1]["role"] == "user":
        messages[-1] = {"role": "user", "content": messages[-1]["content"] + _context_note(ctx)}

    for _ in range(MAX_STEPS):
        with client.messages.stream(model=MODEL, max_tokens=2000, system=SYSTEM,
                                    tools=TOOLS, messages=messages) as stream:
            for ev in stream:
                if ev.type == "content_block_delta" and getattr(ev.delta, "type", "") == "text_delta":
                    yield {"type": "text", "text": ev.delta.text}
            final = stream.get_final_message()
        messages.append({"role": "assistant", "content": final.content})
        tool_uses = [b for b in final.content if b.type == "tool_use"]
        if final.stop_reason != "tool_use" or not tool_uses:
            break
        results = []
        for tu in tool_uses:
            yield {"type": "tool", "name": tu.name, "input": tu.input}
            out = run_tool(tu.name, tu.input, account_fn)
            results.append({"type": "tool_result", "tool_use_id": tu.id,
                            "content": json.dumps(out, ensure_ascii=False)[:20000]})
        messages.append({"role": "user", "content": results})
    yield {"type": "done"}


# ------------------------------------------------------------------ offline fallback
def _find_symbol(text: str, default: str | None) -> str | None:
    t = text.lower()
    for sym, name in NAMES.items():
        base = sym.lower().replace(".jk", "").replace("-usd", "").replace("^", "").replace("=x", "")
        if re.search(rf"\b{re.escape(base)}\b", t) or name.lower() in t:
            return sym
    return default


def _fmt(x, d=2):
    if x is None:
        return "-"
    s = f"{x:,.{d}f}" if abs(x) >= 1 else f"{x:.4f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def offline_analyst(history: list[dict], ctx: dict) -> Iterator[dict]:
    q = history[-1]["content"] if history else ""
    ql = q.lower()
    if any(w in ql for w in ("global", "dunia", "overview", "ringkasan pasar", "semua pasar")):
        yield {"type": "tool", "name": "get_market_overview", "input": {}}
        ov = A.market_overview()
        lines = ["### Ringkasan pasar dunia (1 hari)\n"]
        for g, rows in ov.items():
            ok = [r for r in rows if "chg_1d" in r]
            if ok:
                best = max(ok, key=lambda r: r["chg_1d"])
                worst = min(ok, key=lambda r: r["chg_1d"])
                lines.append(f"- **{g}**: terkuat {best['name']} ({best['chg_1d']*100:+.2f}%), "
                             f"terlemah {worst['name']} ({worst['chg_1d']*100:+.2f}%)")
        lines.append(_offline_footer(ok[0]["source"] if ok else "demo"))
        yield {"type": "text", "text": "\n".join(lines)}
        yield {"type": "done"}
        return

    sym = _find_symbol(q, ctx.get("symbol"))
    iv = ctx.get("interval", "1d") if ctx.get("interval") in ("15m", "1h", "4h", "1d", "1w") else "1d"
    if not sym:
        yield {"type": "text", "text": "Sebutkan aset yang ingin dianalisis, misalnya *BBCA*, *Bitcoin*, atau *S&P 500*."}
        yield {"type": "done"}
        return
    yield {"type": "tool", "name": "get_technical_analysis", "input": {"symbol": sym, "interval": iv}}
    ta = A.technical_analysis(sym, iv)
    if "error" in ta:
        yield {"type": "text", "text": ta["error"]}
        yield {"type": "done"}
        return
    yield {"type": "tool", "name": "run_backtest", "input": {"symbol": sym}}
    bt = A.run_backtest(sym, "1d")["results"]
    ind, rk, lv = ta["indicators"], ta["risk"], ta["levels"]
    passed = [k for k, v in ta["checks"].items() if v]
    failed = [k for k, v in ta["checks"].items() if v is False]
    best = max(bt.items(), key=lambda kv: kv[1]["sharpe"] or -99)
    sup = lv["support"][0] if lv["support"] else rk["atr_stop_long"]
    res = lv["resistance"][0] if lv["resistance"] else rk["atr_stop_short"]
    text = f"""### {ta['name']} ({sym}) · {iv}
**Harga:** {_fmt(ta['price'])} · **Bias teknikal:** {ta['bias']} (skor {ta['bias_score']:.0%})

**Tren & momentum**
- Terpenuhi: {', '.join(passed) or '-'}
- Tidak terpenuhi: {', '.join(failed) or '-'}
- RSI(14) {ind['rsi14']:.1f} · MACD {'di atas' if ind['macd'] > ind['macd_signal'] else 'di bawah'} signal

**Level penting**
- Support: {', '.join(_fmt(x) for x in lv['support']) or '-'}
- Resistance: {', '.join(_fmt(x) for x in lv['resistance']) or '-'}

**Risiko**
- Volatilitas sekarang {rk['vol_annual_now']*100:.1f}%/th vs rata-rata {rk['vol_annual_avg']*100:.1f}%/th → rezim **{rk['regime']}**
- VaR 95% per bar: {rk['var95_per_bar']*100:.2f}% · stop 2×ATR untuk posisi beli: {_fmt(rk['atr_stop_long'])}

**Dua skenario**
- 📈 Naik: tembus {_fmt(res)} dengan volume → target resistance berikutnya. Gagal jika kembali di bawah {_fmt(sup)}.
- 📉 Turun: tembus {_fmt(sup)} → support berikutnya. Gagal jika kembali di atas {_fmt(res)}.

**Backtest harian:** strategi Sharpe tertinggi = **{best[0]}** ({best[1]['sharpe']:.2f}); buy & hold Sharpe {bt['buy_hold']['sharpe']:.2f}.
{_offline_footer(ta['source'])}"""
    yield {"type": "text", "text": text}
    yield {"type": "done"}


def _offline_footer(source: str) -> str:
    src = {"demo": "data DEMO sintetis", "yahoo": "Yahoo Finance (tertunda)", "binance": "Binance real-time"}.get(source, source)
    return (f"\n\n_Sumber: {src}. Mode analis offline berbasis aturan; set `ANTHROPIC_API_KEY` untuk AI agent penuh "
            "yang bisa diajak tanya-jawab. Latihan, bukan nasihat keuangan._")
