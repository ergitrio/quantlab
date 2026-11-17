"""Global watchlist. Symbols use Yahoo Finance tickers; crypto is routed to Binance for real-time data."""

MARKETS = {
    "Indonesia": [
        ("^JKSE", "IHSG"), ("BBCA.JK", "Bank Central Asia"), ("BBRI.JK", "Bank Rakyat Indonesia"),
        ("BMRI.JK", "Bank Mandiri"), ("TLKM.JK", "Telkom Indonesia"), ("ASII.JK", "Astra International"),
        ("GOTO.JK", "GoTo"),
    ],
    "Amerika": [
        ("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq Composite"), ("^DJI", "Dow Jones"),
        ("AAPL", "Apple"), ("MSFT", "Microsoft"), ("NVDA", "NVIDIA"), ("TSLA", "Tesla"),
    ],
    "Asia": [
        ("^N225", "Nikkei 225"), ("^HSI", "Hang Seng"), ("000001.SS", "Shanghai Composite"),
        ("^KS11", "KOSPI"), ("^STI", "Straits Times"), ("^BSESN", "Sensex"),
    ],
    "Eropa": [
        ("^FTSE", "FTSE 100"), ("^GDAXI", "DAX"), ("^FCHI", "CAC 40"), ("^STOXX50E", "Euro Stoxx 50"),
    ],
    "Kripto": [
        ("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum"), ("SOL-USD", "Solana"),
        ("BNB-USD", "BNB"), ("XRP-USD", "XRP"),
    ],
    "Forex": [
        ("USDIDR=X", "USD/IDR"), ("EURUSD=X", "EUR/USD"), ("USDJPY=X", "USD/JPY"), ("GBPUSD=X", "GBP/USD"),
    ],
    "Komoditas": [
        ("GC=F", "Emas"), ("SI=F", "Perak"), ("CL=F", "Minyak WTI"), ("NG=F", "Gas Alam"),
    ],
}

# Rough reference prices so demo mode looks realistic. Not live data.
DEMO_BASE = {
    "^JKSE": 7200, "BBCA.JK": 9200, "BBRI.JK": 4300, "BMRI.JK": 5800, "TLKM.JK": 2900, "ASII.JK": 4900,
    "GOTO.JK": 70, "^GSPC": 6500, "^IXIC": 21500, "^DJI": 45000, "AAPL": 230, "MSFT": 500, "NVDA": 180,
    "TSLA": 350, "^N225": 42000, "^HSI": 25500, "000001.SS": 3800, "^KS11": 3400, "^STI": 4300,
    "^BSESN": 81000, "^FTSE": 9200, "^GDAXI": 24000, "^FCHI": 7800, "^STOXX50E": 5400,
    "BTC-USD": 95000, "ETH-USD": 3500, "SOL-USD": 180, "BNB-USD": 900, "XRP-USD": 2.5,
    "USDIDR=X": 16500, "EURUSD=X": 1.16, "USDJPY=X": 150, "GBPUSD=X": 1.33,
    "GC=F": 3900, "SI=F": 45, "CL=F": 65, "NG=F": 3.2,
}

# FX: Yahoo "XXX=X" = price of 1 USD in XXX. Used to convert everything into the Rupiah paper account.
DEMO_BASE.update({"IDR=X": 16500, "JPY=X": 150, "HKD=X": 7.8, "CNY=X": 7.1, "KRW=X": 1400, "SGD=X": 1.29,
                  "INR=X": 88, "GBP=X": 0.75, "EUR=X": 0.86})

CRYPTO = {s for s, _ in MARKETS["Kripto"]}

_INDEX_CCY = {"^JKSE": "IDR", "^N225": "JPY", "^HSI": "HKD", "000001.SS": "CNY", "^KS11": "KRW", "^STI": "SGD",
              "^BSESN": "INR", "^FTSE": "GBP", "^GDAXI": "EUR", "^FCHI": "EUR", "^STOXX50E": "EUR"}
_SUFFIX_CCY = {".JK": "IDR", ".T": "JPY", ".HK": "HKD", ".SS": "CNY", ".SZ": "CNY", ".KS": "KRW", ".SI": "SGD",
               ".NS": "INR", ".BO": "INR", ".L": "GBP", ".DE": "EUR", ".PA": "EUR", ".AS": "EUR"}


def currency_of(symbol: str) -> str:
    if symbol in _INDEX_CCY:
        return _INDEX_CCY[symbol]
    if symbol.endswith("=X"):                     # forex pair: quote currency
        pair = symbol[:-2]
        return pair[3:6] if len(pair) == 6 else "USD"
    for suf, ccy in _SUFFIX_CCY.items():
        if symbol.endswith(suf):
            return ccy
    return "USD"                                  # US stocks/indices, crypto (-USD), futures (=F)
NAMES = {s: n for group in MARKETS.values() for s, n in group}


def group_of(symbol: str) -> str:
    for g, items in MARKETS.items():
        if any(s == symbol for s, _ in items):
            return g
    return "Lainnya"
