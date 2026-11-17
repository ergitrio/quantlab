import json
import os
from types import SimpleNamespace as NS

import pytest

os.environ["QUANT_DATA"] = "demo"

from fastapi.testclient import TestClient  # noqa: E402

from web import agent  # noqa: E402
from web.markets import currency_of  # noqa: E402
from web.providers import fx_to_idr, get_candles  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_ACCOUNT", str(tmp_path / "acct.json"))
    import importlib
    import web.server as server
    importlib.reload(server)
    return TestClient(server.app)


def test_currency_mapping():
    assert currency_of("BBCA.JK") == "IDR"
    assert currency_of("^N225") == "JPY"
    assert currency_of("BTC-USD") == "USD"
    assert currency_of("EURUSD=X") == "USD"
    assert currency_of("USDIDR=X") == "IDR"
    assert fx_to_idr("IDR") == 1.0 and fx_to_idr("USD") > 10_000


def test_demo_prices_agree_across_intervals():
    a = get_candles("ETH-USD", "1h").rows[-1]["close"]
    b = get_candles("ETH-USD", "1d").rows[-1]["close"]
    assert abs(a / b - 1) < 0.01


def test_candles_are_valid_ohlc(client):
    d = client.get("/api/candles", params={"symbol": "AAPL", "interval": "15m"}).json()
    assert d["source"] == "demo" and d["currency"] == "USD" and len(d["candles"]) == 500
    for r in d["candles"]:
        assert r["low"] <= min(r["open"], r["close"]) and r["high"] >= max(r["open"], r["close"])
    times = [r["time"] for r in d["candles"]]
    assert times == sorted(times) and len(set(times)) == len(times)


def test_bad_interval(client):
    assert client.get("/api/candles", params={"symbol": "AAPL", "interval": "3m"}).status_code == 400


def test_analysis_and_backtest(client):
    a = client.get("/api/analysis", params={"symbol": "^GSPC"}).json()
    assert a["bias"] in {"BULLISH", "BEARISH", "NETRAL"} and "support" in a["levels"]
    b = client.get("/api/backtest", params={"symbol": "BTC-USD", "interval": "1h"}).json()
    assert b["results"]["buy_hold"]["cagr"] is None  # < 1 year of hourly data: no fake annualising


def test_order_converts_to_rupiah_and_needs_reason(client):
    assert client.post("/api/order", json={"symbol": "AAPL", "side": "BUY", "qty": 1, "reason": ""}).status_code == 422
    r = client.post("/api/order", json={"symbol": "AAPL", "side": "BUY", "qty": 2, "reason": "latihan"}).json()
    assert r["currency"] == "USD" and r["price_idr"] == pytest.approx(r["price"] * fx_to_idr("USD"), rel=0.01)
    acct = r["account"]
    assert acct["cash"] == pytest.approx(10_000_000 - 2 * r["price_idr"] * 1.0015, rel=1e-6)
    assert acct["journal"][0]["reason"] == "latihan"
    too_big = client.post("/api/order", json={"symbol": "BTC-USD", "side": "BUY", "qty": 1, "reason": "x" * 5})
    assert too_big.status_code == 400  # 1 BTC is far more than Rp 10 juta


def test_websocket_streams_candles(client):
    with client.websocket_connect("/ws/candles?symbol=SOL-USD&interval=1m") as ws:
        m = ws.receive_json()
    assert m["symbol"] == "SOL-USD" and m["candles"][0]["close"] > 0


def _sse(resp):
    return [json.loads(line[5:]) for line in resp.text.split("\n\n") if line.startswith("data:")]


def test_agent_offline_fallback(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    evs = _sse(client.post("/api/agent", json={"messages": [{"role": "user", "content": "analisis BBRI"}],
                                               "symbol": "AAPL", "interval": "1d"}))
    assert evs[0] == {"type": "tool", "name": "get_technical_analysis", "input": {"symbol": "BBRI.JK", "interval": "1d"}}
    assert "Bank Rakyat Indonesia" in "".join(e.get("text", "") for e in evs) and evs[-1]["type"] == "done"


# ---- fake Claude client: first turn calls a tool, second turn answers with text
class FakeStream:
    def __init__(self, final, events):
        self.final, self.events = final, events
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __iter__(self): return iter(self.events)
    def get_final_message(self): return self.final


class FakeClient:
    def __init__(self):
        self.calls = []
        self.messages = self
    def stream(self, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:
            tu = NS(type="tool_use", id="t1", name="get_technical_analysis", input={"symbol": "BTC-USD"})
            return FakeStream(NS(content=[tu], stop_reason="tool_use"), [])
        text = "Bitcoin sedang **netral**."
        ev = NS(type="content_block_delta", delta=NS(type="text_delta", text=text))
        return FakeStream(NS(content=[NS(type="text", text=text)], stop_reason="end_turn"), [ev])


def test_agent_tool_loop_with_claude():
    fc = FakeClient()
    evs = list(agent.chat([{"role": "user", "content": "gimana BTC?"}], {"symbol": "BTC-USD", "interval": "1h"}, client=fc))
    assert evs[0]["type"] == "tool" and evs[1] == {"type": "text", "text": "Bitcoin sedang **netral**."}
    second = fc.calls[1]["messages"]   # same list object the agent keeps appending to
    result = next(m["content"][0] for m in second if m["role"] == "user" and isinstance(m["content"], list))
    assert result["type"] == "tool_result" and json.loads(result["content"])["symbol"] == "BTC-USD"
    assert "sedang melihat BTC-USD" in second[0]["content"]  # screen context passed to the model
    assert fc.calls[0]["tools"] and "Jangan pernah mengarang" in fc.calls[0]["system"]
