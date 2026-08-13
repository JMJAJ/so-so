"""Market-data adapter with canonical quote metadata and per-instrument caching."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import yfinance as yf

from instruments import Instrument, is_market_open, resolve_instrument


CACHE_TTL = 10
STALE_AFTER = {"crypto": 15 * 60, "forex": 30 * 60, "stock": 45 * 60, "cfd": 60 * 60, "futures": 60 * 60}
_cache: dict[str, dict] = {}


def pair_to_yfinance(value: str, asset_class: str | None = None) -> str:
    instrument = resolve_instrument(value, asset_class)
    if instrument:
        return instrument.provider_symbol
    normalized = value.strip().upper()
    if "/" in normalized:
        base, quote = normalized.split("/", 1)
        currencies = {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD", "CZK"}
        return f"{base}{quote}=X" if base in currencies and quote in currencies else f"{base}-{quote}"
    return normalized


def _timestamp_seconds(value) -> float:
    try:
        ts = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
        if getattr(ts, "tzinfo", None) is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.timestamp()
    except Exception:
        return time.time()


def _public_quote(instrument: Instrument, cached: dict | None) -> dict:
    now = time.time()
    if not cached:
        return {
            "instrument_id": instrument.id, "symbol": instrument.symbol, "price": None,
            "change": None, "change_pct": None, "as_of": None, "source": "yfinance",
            "delayed": True, "stale": True,
            "market_status": "open" if is_market_open(instrument) else "closed",
        }
    age = max(0, now - cached["as_of_epoch"])
    stale = age > STALE_AFTER[instrument.asset_class]
    return {
        "instrument_id": instrument.id,
        "symbol": instrument.symbol,
        "price": cached["price"],
        "change": cached["change"],
        "change_pct": cached["change_pct"],
        "as_of": datetime.fromtimestamp(cached["as_of_epoch"], timezone.utc).isoformat(),
        "source": "yfinance",
        "delayed": True,
        "stale": stale,
        "market_status": "open" if is_market_open(instrument) else "closed",
    }


def fetch_quotes(instrument_ids: list[str]) -> dict[str, dict]:
    instruments = [resolve_instrument(value) for value in instrument_ids]
    instruments = [item for item in instruments if item is not None]
    now = time.time()
    missing = [item for item in instruments if item.id not in _cache or now - _cache[item.id]["fetched_at"] >= CACHE_TTL]
    if missing:
        _refresh(missing)
    return {item.id: _public_quote(item, _cache.get(item.id)) for item in instruments}


def _refresh(instruments: list[Instrument]) -> None:
    provider_map: dict[str, list[Instrument]] = {}
    for instrument in instruments:
        provider_map.setdefault(instrument.provider_symbol, []).append(instrument)
    provider_symbols = sorted(provider_map)
    fetched_at = time.time()

    for start in range(0, len(provider_symbols), 12):
        batch = provider_symbols[start:start + 12]
        try:
            frame = yf.download(
                batch, period="5d", interval="5m", group_by="ticker",
                auto_adjust=True, threads=True, progress=False,
            )
        except Exception:
            continue
        if frame is None or frame.empty:
            continue
        multi = isinstance(frame.columns, pd.MultiIndex)
        for provider_symbol in batch:
            try:
                if multi:
                    if provider_symbol not in frame.columns.get_level_values(0):
                        continue
                    closes = frame[provider_symbol]["Close"].dropna()
                elif len(batch) == 1 and "Close" in frame.columns:
                    closes = frame["Close"].dropna()
                else:
                    continue
                if closes.empty:
                    continue
                price = float(closes.iloc[-1])
                previous = float(closes.iloc[-2]) if len(closes) > 1 else price
                epoch = _timestamp_seconds(closes.index[-1])
                change = price - previous
                payload = {
                    "price": price,
                    "change": change,
                    "change_pct": (change / previous * 100) if previous else 0,
                    "as_of_epoch": epoch,
                    "fetched_at": fetched_at,
                }
                for instrument in provider_map[provider_symbol]:
                    _cache[instrument.id] = payload.copy()
            except Exception:
                continue


def fetch_quote(instrument_id: str) -> dict | None:
    instrument = resolve_instrument(instrument_id)
    if not instrument:
        return None
    return fetch_quotes([instrument.id]).get(instrument.id)


def fetch_prices(symbols: list[str]) -> dict[str, dict]:
    """Compatibility shape for technical-analysis and legacy endpoints."""
    resolved = [(symbol, resolve_instrument(symbol)) for symbol in symbols]
    quote_map = fetch_quotes([item.id for _, item in resolved if item])
    result: dict[str, dict] = {}
    for symbol, instrument in resolved:
        if not instrument:
            continue
        quote = quote_map.get(instrument.id)
        if quote and quote["price"] is not None:
            result[symbol] = {
                "price": quote["price"], "change": quote["change"],
                "changePct": quote["change_pct"], "prevClose": quote["price"] - (quote["change"] or 0),
                "as_of": quote["as_of"], "stale": quote["stale"], "source": quote["source"],
            }
    return result


def fetch_single(pair: str, asset_class: str | None = None) -> Optional[float]:
    instrument = resolve_instrument(pair, asset_class)
    if not instrument:
        return None
    quote = fetch_quote(instrument.id)
    return quote["price"] if quote and quote["price"] is not None else None


def provider_health() -> dict:
    sample = fetch_quote("crypto:btc-usd")
    return {
        "provider": "yfinance",
        "ok": bool(sample and sample["price"] is not None),
        "sample_as_of": sample.get("as_of") if sample else None,
        "delayed": True,
    }
