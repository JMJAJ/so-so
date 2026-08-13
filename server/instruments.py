"""Canonical instrument catalog for the local NEXUS paper terminal.

Display symbols are intentionally separated from provider symbols and stable IDs.
That keeps ambiguous labels (for example Barrick Gold and gold futures) from
sharing prices or ledger rows.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal


AssetClass = Literal["forex", "stock", "crypto", "cfd", "futures"]
Eligibility = Literal["trade_enabled", "research_only"]


@dataclass(frozen=True)
class Instrument:
    id: str
    symbol: str
    name: str
    asset_class: AssetClass
    provider_symbol: str
    quote_currency: str = "USD"
    multiplier: float = 1.0
    tick_size: float = 0.01
    session: str = "us_equities"
    eligibility: Eligibility = "trade_enabled"
    proxy: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _forex(symbol: str) -> Instrument:
    base, quote = symbol.split("/")
    return Instrument(
        id=f"forex:{base.lower()}{quote.lower()}",
        symbol=symbol,
        name=f"{base}/{quote}",
        asset_class="forex",
        provider_symbol=f"{base}{quote}=X",
        quote_currency=quote,
        tick_size=0.001 if quote == "JPY" else 0.0001,
        session="forex",
    )


def _stock(symbol: str, name: str) -> Instrument:
    return Instrument(
        id=f"stock:{symbol.lower()}",
        symbol=symbol,
        name=name,
        asset_class="stock",
        provider_symbol=symbol,
        session="us_equities",
    )


def _crypto(symbol: str, name: str) -> Instrument:
    base, quote = symbol.split("/")
    return Instrument(
        id=f"crypto:{base.lower()}-{quote.lower()}",
        symbol=symbol,
        name=name,
        asset_class="crypto",
        provider_symbol=f"{base}-{quote}",
        quote_currency=quote,
        tick_size=0.0001 if base == "XRP" else 0.01,
        session="always",
    )


def _research(
    instrument_id: str,
    symbol: str,
    name: str,
    asset_class: AssetClass,
    provider_symbol: str,
    *,
    multiplier: float = 1.0,
    tick_size: float = 0.01,
    session: str = "futures",
) -> Instrument:
    return Instrument(
        id=instrument_id,
        symbol=symbol,
        name=name,
        asset_class=asset_class,
        provider_symbol=provider_symbol,
        multiplier=multiplier,
        tick_size=tick_size,
        session=session,
        eligibility="research_only",
        proxy=True,
    )


INSTRUMENTS: tuple[Instrument, ...] = (
    *(_forex(s) for s in (
        "EUR/USD", "GBP/USD", "GBP/JPY", "USD/JPY", "USD/CHF",
        "AUD/USD", "EUR/GBP", "NZD/USD", "USD/CAD", "EUR/JPY",
    )),
    *(
        _stock(symbol, name)
        for symbol, name in (
            ("NVDA", "NVIDIA"), ("AAPL", "Apple"), ("TSLA", "Tesla"),
            ("MSFT", "Microsoft"), ("GOOGL", "Alphabet"), ("META", "Meta"),
            ("AMZN", "Amazon"), ("AMD", "AMD"), ("AVGO", "Broadcom"),
            ("PLTR", "Palantir"), ("COIN", "Coinbase"), ("NFLX", "Netflix"),
            ("JPM", "JPMorgan"), ("GOLD", "Barrick Gold"), ("BA", "Boeing"),
            ("SPY", "SPDR S&P 500 ETF"), ("QQQ", "Invesco QQQ"),
            ("IWM", "iShares Russell 2000 ETF"), ("GLD", "SPDR Gold Shares"),
        )
    ),
    _crypto("BTC/USD", "Bitcoin"),
    _crypto("ETH/USD", "Ethereum"),
    _crypto("SOL/USD", "Solana"),
    _crypto("XRP/USD", "XRP"),
    _research("cfd:us500", "US500", "S&P 500 proxy", "cfd", "^GSPC", session="us_equities"),
    _research("cfd:nas100", "NAS100", "Nasdaq Composite proxy", "cfd", "^IXIC", session="us_equities"),
    _research("cfd:us30", "US30", "Dow Jones proxy", "cfd", "^DJI", session="us_equities"),
    _research("cfd:ger40", "GER40", "DAX proxy", "cfd", "^GDAXI", session="us_equities"),
    _research("cfd:jpn225", "JPN225", "Nikkei 225 proxy", "cfd", "^N225", session="us_equities"),
    _research("cfd:xauusd", "XAU/USD", "Gold futures proxy", "cfd", "GC=F"),
    _research("cfd:xagusd", "XAG/USD", "Silver futures proxy", "cfd", "SI=F"),
    _research("cfd:wti", "WTI", "WTI futures proxy", "cfd", "CL=F"),
    _research("cfd:natgas", "NATGAS", "Natural gas futures proxy", "cfd", "NG=F"),
    _research("future:es", "ES", "E-mini S&P 500", "futures", "ES=F", multiplier=50, tick_size=0.25),
    _research("future:nq", "NQ", "E-mini Nasdaq 100", "futures", "NQ=F", multiplier=20, tick_size=0.25),
    _research("future:ym", "YM", "E-mini Dow", "futures", "YM=F", multiplier=5, tick_size=1.0),
    _research("future:rty", "RTY", "E-mini Russell 2000", "futures", "RTY=F", multiplier=50, tick_size=0.1),
    _research("future:zb", "ZB", "30-Year Treasury", "futures", "ZB=F", multiplier=1000, tick_size=0.03125),
    _research("future:zn", "ZN", "10-Year Treasury", "futures", "ZN=F", multiplier=1000, tick_size=0.015625),
    _research("future:zc", "ZC", "Corn", "futures", "ZC=F", multiplier=50, tick_size=0.25),
    _research("future:zs", "ZS", "Soybeans", "futures", "ZS=F", multiplier=50, tick_size=0.25),
    _research("future:zw", "ZW", "Wheat", "futures", "ZW=F", multiplier=50, tick_size=0.25),
    _research("future:gc", "GC", "Gold", "futures", "GC=F", multiplier=100, tick_size=0.1),
    _research("future:si", "SI", "Silver", "futures", "SI=F", multiplier=5000, tick_size=0.005),
    _research("future:cl", "CL", "WTI Crude Oil", "futures", "CL=F", multiplier=1000, tick_size=0.01),
)

BY_ID = {instrument.id: instrument for instrument in INSTRUMENTS}


def get_instrument(instrument_id: str) -> Instrument | None:
    return BY_ID.get(instrument_id.strip().lower())


def find_instrument(symbol: str, asset_class: str | None = None) -> Instrument | None:
    normalized = symbol.strip().upper()
    for instrument in INSTRUMENTS:
        if instrument.symbol == normalized and (asset_class is None or instrument.asset_class == asset_class):
            return instrument
    return None


def resolve_instrument(value: str, asset_class: str | None = None) -> Instrument | None:
    return get_instrument(value) or find_instrument(value, asset_class)


def is_market_open(instrument_or_class: Instrument | str) -> bool:
    if isinstance(instrument_or_class, Instrument):
        session = instrument_or_class.session
    else:
        session = {
            "crypto": "always", "forex": "forex", "futures": "futures",
            "stock": "us_equities", "cfd": "us_equities",
        }.get(instrument_or_class, "always")

    now = datetime.now(timezone.utc)
    weekday = now.weekday()
    minute = now.hour * 60 + now.minute
    if session == "always":
        return True
    if session == "forex":
        return not (weekday == 5 or (weekday == 4 and minute >= 22 * 60) or (weekday == 6 and minute < 22 * 60))
    if session == "futures":
        return not (weekday == 5 or (weekday == 4 and minute >= 22 * 60) or (weekday == 6 and minute < 23 * 60))
    if session == "us_equities":
        return weekday < 5 and 13 * 60 + 30 <= minute <= 20 * 60
    return True


def public_catalog() -> list[dict]:
    return [{**instrument.to_dict(), "market_status": "open" if is_market_open(instrument) else "closed"} for instrument in INSTRUMENTS]
