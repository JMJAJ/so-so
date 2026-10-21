"""Instrument universe: what NEXUS researches and paper-trades.

IDs are stable (`stock:aapl`, `etf:spy`, `crypto:btc`, `forex:eurusd`,
`commodity:gold`, `index:vix`). `provider_symbol` is the yfinance ticker.
Index instruments are research-only (regime inputs), everything else is tradable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

AssetClass = Literal["stock", "etf", "crypto", "forex", "commodity", "index"]
ASSET_CLASS_ORDER: tuple[AssetClass, ...] = ("stock", "etf", "crypto", "forex", "commodity", "index")


@dataclass(frozen=True)
class Instrument:
    id: str
    symbol: str
    name: str
    asset_class: AssetClass
    provider_symbol: str
    sector: str = ""
    quote_currency: str = "USD"
    multiplier: float = 1.0
    session: str = "us_equities"
    tradable: bool = True

    @property
    def benchmark_id(self) -> str | None:
        """What 'abnormal return' is measured against for this instrument."""
        if self.asset_class in ("stock", "etf"):
            return None if self.id == "etf:spy" else "etf:spy"
        if self.asset_class == "crypto":
            return None if self.id == "crypto:btc" else "crypto:btc"
        return None

    @property
    def market_id(self) -> str:
        """Which entry of `markets.MARKETS` this instrument trades on."""
        return {"forex": "forex", "futures": "cme", "always": "crypto"}.get(self.session, "nyse")

    def to_dict(self) -> dict:
        return {**asdict(self), "benchmark_id": self.benchmark_id, "market": self.market_id}


SECTOR_ETF = {
    "Technology": "etf:xlk", "Communication": "etf:xlc", "Consumer Discretionary": "etf:xly",
    "Consumer Staples": "etf:xlp", "Financials": "etf:xlf", "Health Care": "etf:xlv",
    "Industrials": "etf:xli", "Energy": "etf:xle", "Utilities": "etf:xlu",
    "Materials": "etf:xlb", "Real Estate": "etf:xlre",
}

_STOCKS: dict[str, list[tuple[str, str]]] = {
    "Technology": [
        ("AAPL", "Apple"), ("MSFT", "Microsoft"), ("NVDA", "NVIDIA"), ("AVGO", "Broadcom"), ("AMD", "AMD"),
        ("ORCL", "Oracle"), ("CRM", "Salesforce"), ("ADBE", "Adobe"), ("CSCO", "Cisco"), ("INTC", "Intel"),
        ("QCOM", "Qualcomm"), ("TXN", "Texas Instruments"), ("IBM", "IBM"), ("MU", "Micron"), ("PLTR", "Palantir"),
        ("NOW", "ServiceNow"), ("AMAT", "Applied Materials"),
    ],
    "Communication": [
        ("GOOGL", "Alphabet"), ("META", "Meta"), ("NFLX", "Netflix"), ("DIS", "Disney"), ("T", "AT&T"),
        ("VZ", "Verizon"), ("CMCSA", "Comcast"),
    ],
    "Consumer Discretionary": [
        ("AMZN", "Amazon"), ("TSLA", "Tesla"), ("HD", "Home Depot"), ("MCD", "McDonald's"), ("NKE", "Nike"),
        ("SBUX", "Starbucks"), ("LOW", "Lowe's"), ("BKNG", "Booking"),
    ],
    "Consumer Staples": [
        ("WMT", "Walmart"), ("PG", "Procter & Gamble"), ("KO", "Coca-Cola"), ("PEP", "PepsiCo"),
        ("COST", "Costco"), ("PM", "Philip Morris"),
    ],
    "Financials": [
        ("JPM", "JPMorgan"), ("BAC", "Bank of America"), ("WFC", "Wells Fargo"), ("GS", "Goldman Sachs"),
        ("MS", "Morgan Stanley"), ("C", "Citigroup"), ("BRK-B", "Berkshire Hathaway"), ("V", "Visa"),
        ("MA", "Mastercard"), ("BLK", "BlackRock"), ("COIN", "Coinbase"), ("PYPL", "PayPal"),
    ],
    "Health Care": [
        ("UNH", "UnitedHealth"), ("JNJ", "Johnson & Johnson"), ("LLY", "Eli Lilly"), ("PFE", "Pfizer"),
        ("MRK", "Merck"), ("ABBV", "AbbVie"), ("TMO", "Thermo Fisher"), ("AMGN", "Amgen"),
    ],
    "Industrials": [
        ("BA", "Boeing"), ("CAT", "Caterpillar"), ("GE", "GE Aerospace"), ("HON", "Honeywell"),
        ("UPS", "UPS"), ("RTX", "RTX"), ("LMT", "Lockheed Martin"), ("DE", "Deere"),
    ],
    "Energy": [("XOM", "Exxon Mobil"), ("CVX", "Chevron"), ("COP", "ConocoPhillips"), ("SLB", "Schlumberger")],
    "Utilities": [("NEE", "NextEra Energy"), ("DUK", "Duke Energy")],
    "Materials": [("LIN", "Linde"), ("FCX", "Freeport-McMoRan"), ("NEM", "Newmont")],
    "Real Estate": [("AMT", "American Tower"), ("PLD", "Prologis")],
}

_ETFS: list[tuple[str, str, str]] = [
    ("SPY", "S&P 500", "Broad"), ("QQQ", "Nasdaq 100", "Broad"), ("IWM", "Russell 2000", "Broad"),
    ("DIA", "Dow Jones", "Broad"), ("EFA", "Developed ex-US", "International"), ("EEM", "Emerging Markets", "International"),
    ("FXI", "China Large Cap", "International"), ("EWJ", "Japan", "International"),
    ("XLK", "Technology Sector", "Technology"), ("XLC", "Communication Sector", "Communication"),
    ("XLY", "Consumer Discretionary Sector", "Consumer Discretionary"), ("XLP", "Consumer Staples Sector", "Consumer Staples"),
    ("XLF", "Financials Sector", "Financials"), ("XLV", "Health Care Sector", "Health Care"),
    ("XLI", "Industrials Sector", "Industrials"), ("XLE", "Energy Sector", "Energy"),
    ("XLU", "Utilities Sector", "Utilities"), ("XLB", "Materials Sector", "Materials"),
    ("XLRE", "Real Estate Sector", "Real Estate"), ("SMH", "Semiconductors", "Technology"),
    ("KRE", "Regional Banks", "Financials"), ("ITA", "Aerospace & Defense", "Industrials"),
    ("TLT", "20+ Year Treasuries", "Bonds"), ("IEF", "7-10 Year Treasuries", "Bonds"),
    ("SHY", "1-3 Year Treasuries", "Bonds"), ("HYG", "High Yield Bonds", "Bonds"), ("LQD", "IG Corporate Bonds", "Bonds"),
    ("TIP", "TIPS", "Bonds"), ("GLD", "Gold", "Commodities"), ("SLV", "Silver", "Commodities"),
    ("USO", "Oil", "Commodities"), ("DBA", "Agriculture", "Commodities"), ("UUP", "US Dollar", "Currency"),
    ("VNQ", "REITs", "Real Estate"),
]

_CRYPTO = [
    ("BTC", "Bitcoin"), ("ETH", "Ethereum"), ("SOL", "Solana"), ("XRP", "XRP"), ("BNB", "BNB"),
    ("ADA", "Cardano"), ("DOGE", "Dogecoin"), ("AVAX", "Avalanche"), ("LINK", "Chainlink"),
]

_FOREX = ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD", "NZD/USD", "EUR/GBP", "EUR/JPY", "USD/CNY"]

_COMMODITIES = [
    ("gold", "GOLD", "Gold futures", "GC=F", 100.0), ("silver", "SILVER", "Silver futures", "SI=F", 5000.0),
    ("copper", "COPPER", "Copper futures", "HG=F", 25000.0), ("wti", "WTI", "WTI crude oil futures", "CL=F", 1000.0),
    ("brent", "BRENT", "Brent crude futures", "BZ=F", 1000.0), ("natgas", "NATGAS", "Natural gas futures", "NG=F", 10000.0),
    ("corn", "CORN", "Corn futures", "ZC=F", 50.0), ("wheat", "WHEAT", "Wheat futures", "ZW=F", 50.0),
    ("soybeans", "SOY", "Soybean futures", "ZS=F", 50.0),
]

_INDICES = [
    ("vix", "VIX", "CBOE Volatility Index", "^VIX"), ("tnx", "US10Y", "10-Year Treasury Yield", "^TNX"),
    ("irx", "US3M", "13-Week T-Bill Yield", "^IRX"), ("dxy", "DXY", "US Dollar Index", "DX-Y.NYB"),
    ("spx", "SPX", "S&P 500 Index", "^GSPC"), ("ndx", "NDX", "Nasdaq 100 Index", "^NDX"),
]


def _build() -> tuple[Instrument, ...]:
    items: list[Instrument] = []
    for sector, names in _STOCKS.items():
        for symbol, name in names:
            items.append(Instrument(f"stock:{symbol.lower()}", symbol, name, "stock", symbol, sector))
    for symbol, name, sector in _ETFS:
        items.append(Instrument(f"etf:{symbol.lower()}", symbol, name, "etf", symbol, sector))
    for symbol, name in _CRYPTO:
        items.append(Instrument(f"crypto:{symbol.lower()}", symbol, name, "crypto", f"{symbol}-USD", "Crypto", session="always"))
    for pair in _FOREX:
        base, quote = pair.split("/")
        items.append(Instrument(
            f"forex:{base.lower()}{quote.lower()}", pair, pair, "forex", f"{base}{quote}=X", "FX",
            quote_currency=quote, session="forex",
        ))
    for key, symbol, name, provider, multiplier in _COMMODITIES:
        items.append(Instrument(f"commodity:{key}", symbol, name, "commodity", provider, "Commodities",
                                multiplier=multiplier, session="futures"))
    for key, symbol, name, provider in _INDICES:
        items.append(Instrument(f"index:{key}", symbol, name, "index", provider, "Index", tradable=False))
    return tuple(items)


INSTRUMENTS: tuple[Instrument, ...] = _build()
BY_ID: dict[str, Instrument] = {item.id: item for item in INSTRUMENTS}
_BY_SYMBOL: dict[str, Instrument] = {}
for _item in INSTRUMENTS:
    _BY_SYMBOL.setdefault(_item.symbol.upper(), _item)
    _BY_SYMBOL.setdefault(_item.provider_symbol.upper(), _item)
    _BY_SYMBOL.setdefault(_item.symbol.replace("/", "").upper(), _item)


def get(instrument_id: str) -> Instrument | None:
    return BY_ID.get(instrument_id.strip().lower())


def resolve(value: str) -> Instrument | None:
    """Accept an id (`stock:aapl`), symbol (`AAPL`, `EUR/USD`, `EURUSD`) or provider ticker (`GC=F`)."""
    if not value:
        return None
    value = value.strip()
    return get(value) or _BY_SYMBOL.get(value.upper()) or _BY_SYMBOL.get(value.upper().replace("-USD", ""))


def require(value: str) -> Instrument:
    item = resolve(value)
    if not item:
        raise KeyError(f"Unknown instrument '{value}'")
    return item


def tradable(enabled_classes: list[str] | None = None) -> list[Instrument]:
    return [
        item for item in INSTRUMENTS
        if item.tradable and (enabled_classes is None or item.asset_class in enabled_classes)
    ]


def sector_etf(item: Instrument) -> str | None:
    return SECTOR_ETF.get(item.sector) if item.asset_class == "stock" else None


def is_market_open(item: Instrument, when: datetime | None = None) -> bool:
    """Regular session of the instrument's market (DST and US holidays included)."""
    from . import markets

    return markets.is_open(item.market_id, when)


def catalog() -> list[dict]:
    return [{**item.to_dict(), "market_open": is_market_open(item)} for item in INSTRUMENTS]
