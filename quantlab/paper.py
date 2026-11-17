"""Paper trading with a trade journal. Zero real money."""
from __future__ import annotations
import json, os
from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class PaperAccount:
    cash: float = 10_000_000.0          # Rp 10 juta virtual
    holdings: dict = field(default_factory=dict)      # sym -> qty
    avg_cost: dict = field(default_factory=dict)      # sym -> avg price
    fee: float = 0.0015
    realized_pnl: float = 0.0
    log: list = field(default_factory=list)
    equity_history: list = field(default_factory=list)  # [(iso time, value)]

    def _rec(self, side, sym, price, qty, reason, pnl=None):
        self.log.append({"time": datetime.now().isoformat(timespec="seconds"), "side": side,
                         "sym": sym, "price": price, "qty": qty, "reason": reason, "pnl": pnl})

    def buy(self, sym: str, price: float, qty: float, reason: str = ""):
        cost = price * qty * (1 + self.fee)
        if qty <= 0 or cost > self.cash:
            raise ValueError("kas tidak cukup atau jumlah tidak valid")
        old = self.holdings.get(sym, 0)
        self.avg_cost[sym] = (self.avg_cost.get(sym, 0) * old + price * qty) / (old + qty)
        self.cash -= cost
        self.holdings[sym] = old + qty
        self._rec("BUY", sym, price, qty, reason)

    def sell(self, sym: str, price: float, qty: float, reason: str = ""):
        if qty <= 0 or self.holdings.get(sym, 0) < qty:
            raise ValueError("kepemilikan tidak cukup")
        proceeds = price * qty * (1 - self.fee)
        pnl = proceeds - self.avg_cost[sym] * qty
        self.realized_pnl += pnl
        self.cash += proceeds
        self.holdings[sym] -= qty
        if self.holdings[sym] == 0:
            del self.holdings[sym]; del self.avg_cost[sym]
        self._rec("SELL", sym, price, qty, reason, pnl)

    def value(self, prices: dict) -> float:
        return self.cash + sum(q * prices[s] for s, q in self.holdings.items())

    def mark(self, prices: dict):
        self.equity_history.append((datetime.now().isoformat(timespec="seconds"), self.value(prices)))

    def win_rate(self) -> float:
        closed = [t["pnl"] for t in self.log if t["pnl"] is not None]
        return sum(p > 0 for p in closed) / len(closed) if closed else 0.0

    def save(self, path):
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls, path):
        if not os.path.exists(path):
            return cls()
        with open(path) as f:
            d = json.load(f)
        d["log"] = [t if isinstance(t, dict) else
                    {"time": "", "side": t[0], "sym": t[1], "price": t[2], "qty": t[3], "reason": "", "pnl": None}
                    for t in d.get("log", [])]
        return cls(**d)
