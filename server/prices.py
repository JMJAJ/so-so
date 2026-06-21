import time
import yfinance as yf
import pandas as pd
from typing import Optional

_cache: dict[str, dict] = {}
_cache_time: float = 0
CACHE_TTL = 10

_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD", "CNY", "HKD", "SEK", "NOK", "MXN", "ZAR", "SGD", "KRW", "INR", "BRL", "RUB", "TRY", "CZK", "PLN"}

_CFD_MAP = {
    "US500": "^GSPC",
    "US30": "^DJI",
    "NAS100": "^IXIC",
    "US2000": "^RUT",
    "GER40": "^GDAXI",
    "UK100": "^FTSE",
    "JPN225": "^N225",
    "XAU/USD": "GC=F",
    "XAG/USD": "SI=F",
    "WTI": "CL=F",
    "BRENT": "BZ=F",
    "NATGAS": "NG=F",
    "COPPER": "HG=F",
    "VIX": "^VIX",
}

_FUTURES_MAP = {
    "ES": "ES=F",    # E-mini S&P 500
    "NQ": "NQ=F",    # E-mini Nasdaq 100
    "YM": "YM=F",    # E-mini Dow
    "RTY": "RTY=F",  # E-mini Russell 2000
    "ZB": "ZB=F",    # 30-Year Treasury Bond
    "ZN": "ZN=F",    # 10-Year Treasury Note
    "ZC": "ZC=F",    # Corn
    "ZS": "ZS=F",    # Soybeans
    "ZW": "ZW=F",    # Wheat
    "GOLD": "GC=F",  # Gold
    "SILVER": "SI=F",  # Silver
    "USOIL": "CL=F",  # Crude Oil WTI
}

def pair_to_yfinance(pair: str) -> str:
    p = pair.strip().upper()
    if p in _CFD_MAP:
        return _CFD_MAP[p]
    if p in _FUTURES_MAP:
        return _FUTURES_MAP[p]
    if "/" in p:
        parts = p.split("/")
        if len(parts) == 2:
            base, quote = parts[0], parts[1]
            if base in _CURRENCIES and quote in _CURRENCIES:
                return f"{base}{quote}=X"
            return f"{base}-{quote}"
    return p

def fetch_prices(symbols: list[str]) -> dict[str, dict]:
    global _cache, _cache_time

    now = time.time()
    if now - _cache_time < CACHE_TTL and _cache:
        return _filter_cache(symbols)

    yf_symbols = {s: pair_to_yfinance(s) for s in symbols}
    yf_tickers = sorted(set(yf_symbols.values()))

    result = {}
    BATCH_SIZE = 10

    for i in range(0, len(yf_tickers), BATCH_SIZE):
        batch = yf_tickers[i:i + BATCH_SIZE]
        try:
            df = yf.download(
                batch,
                period="1mo",
                interval="1h",
                group_by="ticker",
                auto_adjust=True,
                threads=True,
                progress=False,
            )

            if df is not None and not df.empty:
                is_multi = isinstance(df.columns, pd.MultiIndex)

                for yf_sym in batch:
                    try:
                        if is_multi:
                            if yf_sym in df.columns.get_level_values(0):
                                ticker_df = df[yf_sym]
                                if "Close" in ticker_df.columns:
                                    closes = ticker_df["Close"].dropna()
                                else:
                                    continue
                            else:
                                continue
                        else:
                            if len(batch) == 1 and "Close" in df.columns:
                                closes = df["Close"].dropna()
                            else:
                                continue

                        if closes.empty:
                            continue

                        price = float(closes.iloc[-1])
                        prev = float(closes.iloc[-2]) if len(closes) > 1 else price
                        change = price - prev
                        change_pct = (change / prev) * 100 if prev != 0 else 0

                        result[yf_sym] = {
                            "price": price,
                            "change": change,
                            "changePct": change_pct,
                            "prevClose": prev,
                        }
                    except Exception:
                        pass

        except Exception:
            pass

    failed = [t for t in yf_tickers if t not in result]
    if failed:
        try:
            tickers_obj = yf.Tickers(" ".join(failed))
            for yf_sym in failed:
                try:
                    t = tickers_obj.tickers.get(yf_sym)
                    if t is None:
                        continue
                    hist = t.history(period="5d")
                    if hist.empty or "Close" not in hist.columns:
                        continue
                    closes = hist["Close"].dropna()
                    if closes.empty:
                        continue
                    price = float(closes.iloc[-1])
                    prev = float(closes.iloc[-2]) if len(closes) > 1 else price
                    change = price - prev
                    change_pct = (change / prev) * 100 if prev != 0 else 0
                    result[yf_sym] = {
                        "price": price,
                        "change": change,
                        "changePct": change_pct,
                        "prevClose": prev,
                    }
                except Exception:
                    pass
        except Exception:
            pass

    reverse_map: dict[str, list[str]] = {}
    for original, yf_sym in yf_symbols.items():
        reverse_map.setdefault(yf_sym, []).append(original)

    full = {}
    for yf_sym, data in result.items():
        for original in reverse_map.get(yf_sym, []):
            full[original] = data

    _cache = full
    _cache_time = now
    return _filter_cache(symbols)

def fetch_single(pair: str) -> Optional[float]:
    data = fetch_prices([pair])
    return data[pair]["price"] if pair in data else None

def _filter_cache(symbols: list[str]) -> dict[str, dict]:
    return {s: _cache[s] for s in symbols if s in _cache}
