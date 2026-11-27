"""Daily OHLCV history (yfinance) into `bars`, plus cached live quotes."""

from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

import numpy as np
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
# Background refreshes of many instruments (the search list) are kept rarer: each one is a
# minute of downloads on a small CPU that page requests share.
BACKGROUND_TTL = 300
STALE_AFTER = {"crypto": 30 * 60, "forex": 60 * 60, "stock": 60 * 60, "etf": 60 * 60, "commodity": 60 * 60, "index": 60 * 60}
_quotes: dict[str, dict] = {}
# When each instrument was last asked for, found or not: a symbol Yahoo has no intraday bars for
# would otherwise be downloaded again on every single call.
_attempted: dict[str, float] = {}
_background = threading.Lock()


def quotes(instrument_ids: list[str], *, wait: bool = True) -> dict[str, dict]:
    """Latest quotes. With `wait=False` the answer comes from the cache (or the last stored close)
    at once and stale instruments refresh in the background: the whole universe takes about a
    minute to download on the free host, far too long to hold a page request for."""
    items = [item for value in instrument_ids if (item := universe.resolve(value))]
    now = time.time()
    ttl = QUOTE_TTL if wait else BACKGROUND_TTL
    missing = [item for item in items if now - _attempted.get(item.id, 0) >= ttl]
    if missing:
        if wait:
            _refresh_quotes(missing)
        elif _background.acquire(blocking=False):
            threading.Thread(target=_refresh_in_background, args=(missing,), daemon=True, name="quotes").start()
    return {item.id: _public(item) for item in items}


def _refresh_in_background(items: list[Instrument]) -> None:
    try:
        _refresh_quotes(items)
    except Exception as exc:  # keep serving the cached quotes
        db.log("warn", "quotes", f"background refresh failed: {exc}")
    finally:
        _background.release()


def cached_quotes(instrument_ids: list[str]) -> dict[str, dict]:
    """Quotes already in memory, without starting any download. For scans that ride along on
    whatever the pages and the watch job have refreshed anyway."""
    out = {}
    for value in instrument_ids:
        item = universe.resolve(value)
        if item and item.id in _quotes:
            out[item.id] = _public(item)
    return out


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
    extended = cached.get("extended")
    return {
        "instrument_id": item.id,
        "price": cached["price"],
        "change_pct": cached["change_pct"],
        "as_of": datetime.fromtimestamp(cached["as_of_epoch"], timezone.utc).isoformat(timespec="seconds"),
        "stale": age > STALE_AFTER[item.asset_class],
        "market_open": universe.is_market_open(item),
        # Pre-market / after-hours trade newer than the regular-session price. Display only:
        # paper fills, stops and scoring keep using `price` (regular session).
        "extended": None if not extended else {
            "price": extended["price"],
            "change_pct": extended["change_pct"],
            "as_of": datetime.fromtimestamp(extended["as_of_epoch"], timezone.utc).isoformat(timespec="seconds"),
            "session": extended["session"],
        },
    }


def _has_extended_hours(item: Instrument) -> bool:
    from .. import markets

    market = markets.BY_ID.get(item.market_id)
    return bool(market and market.extended)


def _refresh_quotes(items: list[Instrument]) -> None:
    """Latest price from 1-minute bars; instruments with no 1-minute data today (market not
    open yet) fall back to the last 15-minute bar of the past five days. Markets with extended
    hours (US) download two days with pre/post-market bars so the latest regular close and any
    newer extended-hours trade come from one request."""
    fetched_at = time.time()
    for item in items:
        _attempted[item.id] = fetched_at
    extended = [item for item in items if _has_extended_hours(item)]
    regular = [item for item in items if not _has_extended_hours(item)]
    missing = _fetch_quotes(regular, period="1d", interval="1m", fetched_at=fetched_at)
    missing += _fetch_quotes(extended, period="2d", interval="1m", fetched_at=fetched_at, prepost=True)
    if missing:
        _fetch_quotes(missing, period="5d", interval="15m", fetched_at=fetched_at)


def split_sessions(item: Instrument, closes: pd.Series) -> tuple[tuple[float, pd.Timestamp] | None,
                                                                  tuple[float, pd.Timestamp, str] | None]:
    """(last regular-session close, newer extended-hours trade with its session name) from bars
    that include pre/post-market. Either can be None."""
    from .. import markets

    if closes.empty:
        return None, None
    # Vectorised: a quote refresh runs this over ~2 days of 1-minute bars for every US instrument.
    index = pd.DatetimeIndex(closes.index)
    index = (index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")).as_unit("ns")
    spans = markets.intervals(markets.BY_ID[item.market_id], index[0].to_pydatetime() - timedelta(days=1),
                              index[-1].to_pydatetime() + timedelta(days=1))
    stamps = index.asi8
    in_regular = np.zeros(len(index), dtype=bool)
    for a, b in spans:
        in_regular |= (stamps >= pd.Timestamp(a).as_unit("ns").value) & (stamps < pd.Timestamp(b).as_unit("ns").value)
    regular_at = np.flatnonzero(in_regular)
    regular = (float(closes.iloc[regular_at[-1]]), index[regular_at[-1]]) if len(regular_at) else None
    last = len(index) - 1
    if in_regular[last] or (regular and index[last] <= regular[1]):
        return regular, None
    tz = _market_tz(item)
    next_day = regular is None or index[last].astimezone(tz).date() > regular[1].astimezone(tz).date()
    return regular, (float(closes.iloc[last]), index[last], "pre-market" if next_day else "after-hours")


def _market_tz(item: Instrument) -> ZoneInfo:
    from .. import markets

    return ZoneInfo(markets.BY_ID[item.market_id].tz)


def _utc(ts) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _fetch_quotes(items: list[Instrument], *, period: str, interval: str, fetched_at: float,
                  prepost: bool = False) -> list[Instrument]:
    missing: list[Instrument] = []
    for offset in range(0, len(items), BATCH):
        batch = items[offset:offset + BATCH]
        try:
            frame = yf.download(
                [item.provider_symbol for item in batch], period=period, interval=interval,
                group_by="ticker", auto_adjust=True, threads=True, progress=False, prepost=prepost,
            )
        except Exception:
            missing.extend(batch)
            continue
        found: list[tuple[Instrument, float, date, pd.Timestamp, tuple | None]] = []
        for item in batch:
            sub = _frame_for(frame, item.provider_symbol, len(batch))
            if sub is None:
                missing.append(item)
                continue
            closes = sub["Close"]
            if prepost:
                regular, extended = split_sessions(item, closes)
                if regular is None:
                    missing.append(item)
                    continue
                price, ts = regular
                day = pd.Timestamp(ts).tz_convert(closes.index[-1].tzinfo or "UTC").date() \
                    if pd.Timestamp(closes.index[-1]).tzinfo else ts.date()
            else:
                ts = pd.Timestamp(closes.index[-1])
                price, day, extended = float(closes.iloc[-1]), ts.date(), None
            found.append((item, price, day, ts, extended))
        references = previous_closes([(item, day) for item, _, day, _, _ in found])
        for item, price, _, ts, extended in found:
            reference = references.get(item.id)
            ts = _utc(ts)
            _quotes[item.id] = {
                "price": price,
                "change_pct": (price / reference - 1) * 100 if reference else None,
                "as_of_epoch": ts.timestamp(),
                "fetched_at": fetched_at,
                "extended": None if extended is None else {
                    "price": extended[0],
                    "change_pct": (extended[0] / price - 1) * 100 if price else None,
                    "as_of_epoch": extended[1].timestamp(),
                    "session": extended[2],
                },
            }
    return missing


# Previous session close per instrument, keyed by the quote's session day: one lookup per day.
_prev_close: dict[str, tuple[date, float | None]] = {}


def previous_closes(items: list[tuple[Instrument, date]]) -> dict[str, float | None]:
    """Close of the last session before `day` for each instrument. Stored daily bars are used
    when they reach that session; otherwise (the daily job hasn't run, e.g. after the server was
    off for a while) Yahoo's daily bars are asked, so "change today" never depends on our own
    ingestion being up to date."""
    out: dict[str, float | None] = {}
    ask: list[tuple[Instrument, date]] = []
    for item, day in items:
        cached = _prev_close.get(item.id)
        if cached and cached[0] == day and cached[1] is not None:
            out[item.id] = cached[1]
            continue
        row = db.one("SELECT date, close FROM bars WHERE instrument_id=? AND date<? ORDER BY date DESC LIMIT 1",
                     (item.id, day.isoformat()))
        # Stored history reaching the previous weekday (or close: weekends, holidays) is current.
        if row and (day - date.fromisoformat(row["date"])).days <= _session_gap(day, item):
            out[item.id] = row["close"]
            _prev_close[item.id] = (day, row["close"])
        else:
            ask.append((item, day))
    for offset in range(0, len(ask), BATCH):
        batch = ask[offset:offset + BATCH]
        try:
            frame = yf.download([item.provider_symbol for item, _ in batch], period="10d", interval="1d",
                                group_by="ticker", auto_adjust=True, threads=True, progress=False)
        except Exception:
            frame = None
        for item, day in batch:
            sub = _frame_for(frame, item.provider_symbol, len(batch)) if frame is not None else None
            value = None
            if sub is not None:
                before = [float(close) for ts, close in sub["Close"].items() if pd.Timestamp(ts).date() < day]
                value = before[-1] if before else None
            out[item.id] = value
            _prev_close[item.id] = (day, value)
    return out


def _session_gap(day: date, item: Instrument) -> int:
    """Calendar days back to the previous session: 1 for 24/7 crypto, up to 4 over a long weekend."""
    if item.asset_class == "crypto":
        return 1
    return 3 if day.weekday() == 0 else 1 if day.weekday() < 5 else 2


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
    sweep_intraday()
    return rows


INTRADAY_KEEP = 600  # seconds an unused chart stays in memory (a revisit within it is instant)


def sweep_intraday() -> None:
    """Forget intraday bars nobody has looked at for a while (~1000 bars per asset and span)."""
    now = time.time()
    for key, (at, _rows) in list(_intraday.items()):
        if now - at > INTRADAY_KEEP:
            _intraday.pop(key, None)


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
