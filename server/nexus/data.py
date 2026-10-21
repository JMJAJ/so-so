"""Read-side helpers: load stored history as pandas objects (cached per process)."""

from __future__ import annotations

import threading
import time

import pandas as pd

from . import db

_cache: dict[tuple, tuple[float, object]] = {}
_lock = threading.Lock()
TTL = 300


def _cached(key: tuple, loader):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < TTL:
            return hit[1]
    value = loader()
    with _lock:
        _cache[key] = (now, value)
    return value


def invalidate() -> None:
    with _lock:
        _cache.clear()


def closes(start: str | None = None) -> pd.DataFrame:
    """Wide frame of daily closes: index = date, columns = instrument_id. Forward-filled across
    calendars (crypto trades weekends) only inside the frame, never beyond the last real print."""

    def load() -> pd.DataFrame:
        frame = pd.DataFrame(db.rows("SELECT instrument_id, date, close FROM bars"))
        if frame.empty:
            return pd.DataFrame()
        wide = frame.pivot(index="date", columns="instrument_id", values="close")
        wide.index = pd.to_datetime(wide.index)
        wide = wide.sort_index()
        # Keep business days only so equities, FX and crypto share one calendar.
        wide = wide[wide.index.dayofweek < 5]
        last_valid = wide.apply(lambda col: col.last_valid_index())
        filled = wide.ffill(limit=3)
        for column, last in last_valid.items():
            if last is not None:
                filled.loc[filled.index > last, column] = float("nan")
        return filled

    wide = _cached(("closes",), load)
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
