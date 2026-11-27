"""Read-side helpers: load stored history as pandas objects (cached per process)."""

from __future__ import annotations

import threading
import time

import numpy as np
import pandas as pd

from . import db, memory

_cache: dict[tuple, tuple[float, object, float]] = {}  # key -> (stored at, value, ttl)
_lock = threading.Lock()
_loading: dict[tuple, threading.Lock] = {}
TTL = 300
# Reads skip expired entries but never removed them, so keys that include a time bucket (asset
# simulations) piled up for the life of the process. Inserts sweep at most this often.
SWEEP_EVERY = 60.0
_swept = {"at": 0.0}
# Daily bars change only when the daily job or a research import runs, and both call
# invalidate(); the TTL is just a safety net. Rebuilding the wide frame is the most
# memory-hungry thing the server does, so it must not happen every few minutes.
CLOSES_TTL = 6 * 3600


def _cached(key: tuple, loader, ttl: float = TTL):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        key_lock = _loading.setdefault(key, threading.Lock())
    if now - _swept["at"] >= SWEEP_EVERY:
        sweep()
    # One loader per key: concurrent callers (analyst + import + page loads) wait for it
    # instead of each building their own copy at the same time.
    with key_lock:
        with _lock:
            hit = _cache.get(key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
        value = loader()
        with _lock:
            _cache[key] = (time.time(), value, ttl)
    return value


def sweep() -> int:
    """Drop expired entries (and the per-key loader locks nobody holds). Returns how many."""
    now = time.time()
    with _lock:
        _swept["at"] = now
        expired = [k for k, (at, _value, ttl) in _cache.items() if now - at >= ttl]
        for key in expired:
            del _cache[key]
        for key in [k for k, lock in _loading.items() if k not in _cache and not lock.locked()]:
            del _loading[key]
    return len(expired)


def invalidate() -> None:
    with _lock:
        _cache.clear()


def closes(start: str | None = None) -> pd.DataFrame:
    """Wide frame of daily closes: index = date, columns = instrument_id. Forward-filled across
    calendars (crypto trades weekends) only inside the frame, never beyond the last real print."""

    def load() -> pd.DataFrame:
        # One instrument at a time, straight into float arrays: building the frame from one
        # dict per bar (~400k of them) peaked at ~180 MB for what is a ~3 MB table.
        conn = db.connect()
        try:
            ids = [row[0] for row in conn.execute("SELECT DISTINCT instrument_id FROM bars")]
            columns = {}
            for instrument_id in ids:
                rows = conn.execute("SELECT date, close FROM bars WHERE instrument_id=? ORDER BY date",
                                    (instrument_id,)).fetchall()
                if rows:
                    columns[instrument_id] = pd.Series(
                        np.fromiter((r[1] if r[1] is not None else np.nan for r in rows), dtype=float,
                                    count=len(rows)),
                        index=pd.DatetimeIndex([r[0] for r in rows]),
                    )
        finally:
            conn.close()
        if not columns:
            return pd.DataFrame()
        wide = pd.DataFrame(columns).sort_index(axis=1)
        wide.index.name = "date"
        wide.columns.name = "instrument_id"
        wide = wide.sort_index()
        # Keep business days only so equities, FX and crypto share one calendar.
        wide = wide[wide.index.dayofweek < 5]
        last_valid = wide.apply(lambda col: col.last_valid_index())
        filled = wide.ffill(limit=3)
        for column, last in last_valid.items():
            if last is not None:
                filled.loc[filled.index > last, column] = float("nan")
        return filled

    def load_and_trim() -> pd.DataFrame:
        frame = load()
        memory.trim()
        return frame

    wide = _cached(("closes",), load_and_trim, ttl=CLOSES_TTL)
    if start and not wide.empty:
        return wide[wide.index >= pd.Timestamp(start)]
    return wide


def ohlcv(instrument_id: str, start: str | None = None) -> pd.DataFrame:
    sql = "SELECT date, open, high, low, close, volume FROM bars WHERE instrument_id=?"
    params: list = [instrument_id]
    if start:
        sql += " AND date>=?"
        params.append(start)
    frame = pd.DataFrame(db.rows(sql + " ORDER BY date", params))
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date")


def macro(series_id: str) -> pd.Series:
    def load() -> pd.Series:
        frame = pd.DataFrame(db.rows("SELECT date, value FROM macro_series WHERE series_id=? ORDER BY date", (series_id,)))
        if frame.empty:
            return pd.Series(dtype=float)
        return pd.Series(frame["value"].values, index=pd.to_datetime(frame["date"]), name=series_id)

    return _cached(("macro", series_id), load)


def theme_share(theme: str) -> pd.Series:
    """Theme intensity normalised by total GDELT volume that day (volume drifts over the years)."""

    def load() -> pd.Series:
        frame = pd.DataFrame(db.rows(
            """SELECT t.date, t.count * 1.0 / NULLIF(tot.count, 0) AS share
               FROM theme_series t JOIN theme_series tot ON tot.theme='_total' AND tot.date=t.date
               WHERE t.theme=? ORDER BY t.date""",
            (theme,),
        ))
        if frame.empty:
            return pd.Series(dtype=float)
        return pd.Series(frame["share"].values, index=pd.to_datetime(frame["date"]), name=theme)

    return _cached(("theme", theme), load)


def events_frame() -> pd.DataFrame:
    def load() -> pd.DataFrame:
        frame = pd.DataFrame(db.rows("SELECT id, type, instrument_id, scope, date, magnitude, surprise, title FROM events"))
        if not frame.empty:
            frame["date"] = pd.to_datetime(frame["date"])
        return frame

    return _cached(("events",), load)
