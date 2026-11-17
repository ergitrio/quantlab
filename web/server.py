"""Quant Desk web server.

Run:  uvicorn web.server:app --reload        (from the project root)
Then open http://localhost:8000
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from quantlab.paper import PaperAccount

from . import agent
from . import analysis as A
from .markets import MARKETS, NAMES, currency_of
from .providers import INTERVAL_SECONDS, fx_to_idr, get_candles, last_price, latest, mode, poll_seconds

STATIC = Path(__file__).parent / "static"
ACCOUNT_FILE = os.environ.get("QUANT_ACCOUNT", "paper_account.json")
_lock = threading.Lock()

app = FastAPI(title="Quant Desk")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
def config():
    return {"data_mode": mode(), "ai": "claude" if agent.has_api_key() else "offline",
            "model": agent.MODEL if agent.has_api_key() else None, "intervals": list(INTERVAL_SECONDS)}


@app.get("/api/markets")
def markets():
    return {g: [{"symbol": s, "name": n} for s, n in items] for g, items in MARKETS.items()}


_pool = ThreadPoolExecutor(max_workers=12)
_quotes_cache: dict = {"t": 0.0, "data": None}


def _quote(sym: str):
    try:
        rows = get_candles(sym, "1d", limit=5).rows
        return sym, {"price": rows[-1]["close"], "chg": rows[-1]["close"] / rows[-2]["close"] - 1}
    except Exception:
        return sym, None


@app.get("/api/quotes")
def quotes():
    """Compact last price + 1d change for the whole watchlist (fetched in parallel, cached briefly)."""
    ttl = 0 if mode() == "demo" else 20
    if _quotes_cache["data"] and time.time() - _quotes_cache["t"] < ttl:
        return _quotes_cache["data"]
    syms = [s for items in MARKETS.values() for s, _ in items]
    data = dict(_pool.map(_quote, syms))
    _quotes_cache.update(t=time.time(), data=data)
    return data


@app.get("/api/candles")
def candles(symbol: str, interval: str = "1d", limit: int = Query(500, le=1000)):
    try:
        c = get_candles(symbol, interval, limit)
    except ValueError as e:
        raise HTTPException(400, str(e))
    df = c.to_frame()
    return {"symbol": symbol, "name": NAMES.get(symbol, symbol), "interval": interval, "source": c.source,
            "currency": currency_of(symbol),
            "delayed": c.delayed, "candles": c.rows, "indicators": A.indicator_series(df) if len(df) else {}}


@app.get("/api/analysis")
def analysis(symbol: str, interval: str = "1d"):
    return A.technical_analysis(symbol, interval)


@app.get("/api/backtest")
def backtest(symbol: str, interval: str = "1d"):
    return A.run_backtest(symbol, interval)


@app.get("/api/montecarlo")
def montecarlo(symbol: str, strategy: str = "buy_hold", horizon: int = 252):
    return A.monte_carlo(symbol, strategy, horizon)


@app.get("/api/overview")
def overview():
    return A.market_overview()


@app.get("/api/fx")
def fx(symbol: str):
    ccy = currency_of(symbol)
    return {"symbol": symbol, "currency": ccy, "fx_to_idr": fx_to_idr(ccy)}


# ------------------------------------------------------------------ paper trading (account is in Rupiah)
def _price_idr(symbol: str) -> tuple[float, float, str]:
    ccy = currency_of(symbol)
    native = last_price(symbol)
    return native * fx_to_idr(ccy), native, ccy


def _account_view() -> dict:
    acct = PaperAccount.load(ACCOUNT_FILE)
    prices = {s: _price_idr(s)[0] for s in acct.holdings}
    positions = [{"symbol": s, "name": NAMES.get(s, s), "qty": q, "avg_cost": acct.avg_cost.get(s, 0),
                  "price": prices[s], "value": q * prices[s], "pnl": q * (prices[s] - acct.avg_cost.get(s, 0))}
                 for s, q in acct.holdings.items()]
    equity = acct.cash + sum(p["value"] for p in positions)
    return {"cash": acct.cash, "equity": equity, "start": 10_000_000, "realized_pnl": acct.realized_pnl,
            "win_rate": acct.win_rate(), "positions": positions, "journal": acct.log[-50:][::-1],
            "note": "Uang virtual dalam Rupiah. Aset non-Rupiah dikonversi dengan kurs terakhir."}


@app.get("/api/account")
def account():
    return _account_view()


class Order(BaseModel):
    symbol: str
    side: str = Field(pattern="^(BUY|SELL)$")
    qty: float = Field(gt=0)
    reason: str = Field(min_length=3, description="Alasan wajib — jurnal trading")


@app.post("/api/order")
def order(o: Order):
    try:
        price, native, ccy = _price_idr(o.symbol)
    except Exception as e:
        raise HTTPException(400, f"Harga {o.symbol} tidak tersedia: {e}")
    with _lock:
        acct = PaperAccount.load(ACCOUNT_FILE)
        try:
            (acct.buy if o.side == "BUY" else acct.sell)(o.symbol, price, o.qty, o.reason)
        except ValueError as e:
            raise HTTPException(400, str(e))
        acct.log[-1].update(native_price=native, currency=ccy)
        acct.save(ACCOUNT_FILE)
    return {"ok": True, "price_idr": price, "price": native, "currency": ccy, "account": _account_view()}


@app.post("/api/account/reset")
def reset():
    with _lock:
        PaperAccount().save(ACCOUNT_FILE)
    return _account_view()


# ------------------------------------------------------------------ AI agent (SSE stream)
class ChatReq(BaseModel):
    messages: list[dict]
    symbol: str | None = None
    interval: str | None = None


@app.post("/api/agent")
def agent_chat(req: ChatReq):
    def gen():
        try:
            for ev in agent.chat(req.messages[-20:], {"symbol": req.symbol, "interval": req.interval},
                                 account_fn=_account_view):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:  # surface API errors (bad key, rate limit) to the UI
            yield f"data: {json.dumps({'type': 'error', 'text': f'{type(e).__name__}: {e}'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ------------------------------------------------------------------ live candles
@app.websocket("/ws/candles")
async def ws_candles(ws: WebSocket, symbol: str, interval: str = "1d"):
    await ws.accept()
    try:
        c = await asyncio.to_thread(get_candles, symbol, interval)
        wait = poll_seconds(c.source)
        while True:
            await asyncio.sleep(wait)
            try:
                rows = await asyncio.to_thread(latest, symbol, interval, c.source)
            except Exception:
                continue
            await ws.send_json({"symbol": symbol, "interval": interval, "source": c.source, "candles": rows})
    except WebSocketDisconnect:
        pass
