"""Daily OHLCV history (yfinance) into `bars`, plus cached live quotes."""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from typing import Callable

import pandas as pd
import yfinance as yf

from .. import config, db, universe
from ..universe import Instrument

BATCH = 20


def _frame_for(frame: pd.DataFrame, provider_symbol: str, batch_size: int) -> pd.DataFrame | None:
    if frame is None or frame.empty:
        return None
    if isinstance(frame.columns, pd.MultiIndex):
        if provider_symbol not in frame.columns.get_level_values(0):
            return None
        sub = frame[provider_symbol]
    elif batch_size == 1:
        sub = frame
    else:
        return None
    sub = sub.dropna(subset=["Close"])
    return sub if not sub.empty else None


def _store(instrument: Instrument, frame: pd.DataFrame) -> int:
    records = []
    for ts, row in frame.iterrows():
        day = pd.Timestamp(ts).date().isoformat()
        records.append((
            instrument.id, day,
            _num(row.get("Open")), _num(row.get("High")), _num(row.get("Low")),
            float(row["Close"]), _num(row.get("Volume")),
        ))
    db.executemany(
        """INSERT INTO bars(instrument_id,date,open,high,low,close,volume) VALUES(?,?,?,?,?,?,?)
           ON CONFLICT(instrument_id,date) DO UPDATE SET open=excluded.open, high=excluded.high,
           low=excluded.low, close=excluded.close, volume=excluded.volume""",
        records,
    )
    return len(records)


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(number) else number


def last_bar_dates() -> dict[str, str]:
    return {row["instrument_id"]: row["d"] for row in db.rows("SELECT instrument_id, MAX(date) d FROM bars GROUP BY instrument_id")}


def update_bars(
    instruments: list[Instrument] | None = None,
    *,
    years: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Backfill missing history and refresh the last few days. Idempotent."""
    instruments = instruments or list(universe.INSTRUMENTS)
    years = years or config.get_int("history_years")
    last = last_bar_dates()
    full_start = (date.today() - timedelta(days=365 * years)).isoformat()
    groups: dict[str, list[Instrument]] = {}
    for item in instruments:
        start = full_start
        if item.id in last:
            start = (date.fromisoformat(last[item.id]) - timedelta(days=7)).isoformat()
        groups.setdefault(start, []).append(item)

    stored, failed = 0, []
    for start, items in groups.items():
        for offset in range(0, len(items), BATCH):
            batch = items[offset:offset + BATCH]
            tickers = [item.provider_symbol for item in batch]
            if progress:
                progress(f"bars {start}: {', '.join(item.symbol for item in batch)}")
            try:
                frame = yf.download(
                    tickers, start=start, interval="1d", group_by="ticker",
                    auto_adjust=True, threads=True, progress=False,
                )
            except Exception as exc:  # network / provider failure: keep going
                db.log("warn", "bars", f"download failed for {tickers}: {exc}")
                failed.extend(item.id for item in batch)
                continue
            for item in batch:
                sub = _frame_for(frame, item.provider_symbol, len(batch))
                if sub is None:
                    failed.append(item.id)
                    continue
                stored += _store(item, sub)
    return {"rows": stored, "failed": failed}


# ── Live quotes ──────────────────────────────────────────────────────────────

QUOTE_TTL = 30
# A daily close older than this (weekends + holidays fit) is too stale to measure "today" against.
PREV_CLOSE_MAX_GAP_DAYS = 5
STALE_AFTER = {"crypto": 30 * 60, "forex": 60 * 60, "stock": 60 * 60, "etf": 60 * 60, "commodity": 60 * 60, "index": 60 * 60}
_quotes: dict[str, dict] = {}


def quotes(instrument_ids: list[str]) -> dict[str, dict]:
    items = [item for value in instrument_ids if (item := universe.resolve(value))]
    now = time.time()
    missing = [item for item in items if now - _quotes.get(item.id, {}).get("fetched_at", 0) >= QUOTE_TTL]
    if missing:
        _refresh_quotes(missing)
    return {item.id: _public(item) for item in items}


def quote(instrument_id: str) -> dict | None:
    item = universe.resolve(instrument_id)
    return quotes([item.id])[item.id] if item else None


def _public(item: Instrument) -> dict:
    cached = _quotes.get(item.id)
    if not cached:
        fallback = db.one("SELECT date, close FROM bars WHERE instrument_id=? ORDER BY date DESC LIMIT 1", (item.id,))
        if not fallback:
            return {"instrument_id": item.id, "price": None, "change_pct": None, "as_of": None, "stale": True,
                    "market_open": universe.is_market_open(item)}
        return {"instrument_id": item.id, "price": fallback["close"], "change_pct": None, "as_of": fallback["date"],
                "stale": True, "market_open": universe.is_market_open(item)}
    age = time.time() - cached["as_of_epoch"]
    return {
        "instrument_id": item.id,
        "price": cached["price"],
        "change_pct": cached["change_pct"],
        "as_of": datetime.fromtimestamp(cached["as_of_epoch"], timezone.utc).isoformat(timespec="seconds"),
        "stale": age > STALE_AFTER[item.asset_class],
        "market_open": universe.is_market_open(item),
    }


def _refresh_quotes(items: list[Instrument]) -> None:
    """Latest price from 1-minute bars; instruments with no 1-minute data today (market not
    open yet) fall back to the last 15-minute bar of the past five days."""
    fetched_at = time.time()
    missing = _fetch_quotes(items, period="1d", interval="1m", fetched_at=fetched_at)
    if missing:
        _fetch_quotes(missing, period="5d", interval="15m", fetched_at=fetched_at)


def _fetch_quotes(items: list[Instrument], *, period: str, interval: str, fetched_at: float) -> list[Instrument]:
    missing: list[Instrument] = []
    for offset in range(0, len(items), BATCH):
        batch = items[offset:offset + BATCH]
        try:
            frame = yf.download(
                [item.provider_symbol for item in batch], period=period, interval=interval,
                group_by="ticker", auto_adjust=True, threads=True, progress=False, prepost=False,
            )
        except Exception:
            missing.extend(batch)
            continue
        for item in batch:
            sub = _frame_for(frame, item.provider_symbol, len(batch))
            if sub is None:
                missing.append(item)
                continue
            closes = sub["Close"]
            price = float(closes.iloc[-1])
            quote_day = pd.Timestamp(closes.index[-1]).date()
            prev_day = db.one(
                "SELECT date, close FROM bars WHERE instrument_id=? AND date<? ORDER BY date DESC LIMIT 1",
                (item.id, quote_day.isoformat()),
            )
            if prev_day and (quote_day - date.fromisoformat(prev_day["date"])).days <= PREV_CLOSE_MAX_GAP_DAYS:
                reference = prev_day["close"]
            elif prev_day:
                # Daily bars are behind (the daily job hasn't run): a "change today" against an
                # old close would be weeks of movement labelled as one day. Report it unknown.
                reference = None
            else:
                reference = float(closes.iloc[0])
            ts = pd.Timestamp(closes.index[-1])
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            _quotes[item.id] = {
                "price": price,
                "change_pct": (price / reference - 1) * 100 if reference else None,
                "as_of_epoch": ts.timestamp(),
                "fetched_at": fetched_at,
            }
    return missing


# ── Intraday bars (asset charts) ─────────────────────────────────────────────

INTRADAY = {"1d": ("1d", "1m"), "5d": ("5d", "5m"), "1mo": ("1mo", "30m")}
INTRADAY_TTL = 20
_intraday: dict[tuple[str, str], tuple[float, list[dict]]] = {}


def intraday(item: Instrument, span: str = "1d") -> list[dict]:
    """Intraday OHLCV including pre/after-market, as [{t: epoch seconds, o, h, l, c, v}].
    "1d" is the latest session with 1-minute bars (before today's open, the previous one)."""
    key = (item.id, span)
    cached = _intraday.get(key)
    if cached and time.time() - cached[0] < INTRADAY_TTL:
        return cached[1]
    period, interval = INTRADAY[span]
    frame = _download_intraday(item, period, interval)
    if span == "1d" and frame is None:
        frame = _download_intraday(item, "5d", interval)
        if frame is not None:
            last_day = frame.index[-1].date()
            frame = frame[[ts.date() == last_day for ts in frame.index]]
    rows = [] if frame is None else [
        {"t": int(pd.Timestamp(ts).timestamp()), "o": _num(r["Open"]), "h": _num(r["High"]),
         "l": _num(r["Low"]), "c": _num(r["Close"]), "v": _num(r.get("Volume"))}
        for ts, r in frame.iterrows()
    ]
    _intraday[key] = (time.time(), rows)
    return rows


def _download_intraday(item: Instrument, period: str, interval: str) -> pd.DataFrame | None:
    try:
        frame = yf.download(item.provider_symbol, period=period, interval=interval, auto_adjust=True,
                            progress=False, prepost=True, threads=False)
    except Exception:
        return None
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    if frame is None or frame.empty or "Close" not in frame:
        return None
    frame = frame.dropna(subset=["Close"])
    if frame.empty:
        return None
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")
    return frame


def _num(value) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if value != value else value
