"""Detect structured, dated events with long history.

Every event's `date` is the first trading session in which the market could react.
Event studies enter at that session's close, so measured returns are what you could
actually have captured after learning about the event (no day-0 lookahead).
All thresholds use trailing windows only (point-in-time).
"""

from __future__ import annotations

import hashlib
from datetime import time as dtime

import numpy as np
import pandas as pd
import yfinance as yf

from .. import data, db, universe

SIGMA = 2.5
COOLDOWN = 10


def _id(*parts: object) -> str:
    return "ev_" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _calendar() -> pd.DatetimeIndex:
    closes = data.closes()
    if closes.empty or "etf:spy" not in closes:
        return pd.DatetimeIndex([])
    return closes["etf:spy"].dropna().index


def _snap(calendar: pd.DatetimeIndex, when: pd.Timestamp) -> pd.Timestamp | None:
    when = when.normalize()
    if len(calendar) == 0 or when < calendar[0] or when > calendar[-1] + pd.Timedelta(days=4):
        return None
    pos = calendar.searchsorted(when)
    return calendar[pos] if pos < len(calendar) else None


def _cooldown(flags: pd.Series, days: int = COOLDOWN) -> list[pd.Timestamp]:
    picked: list[pd.Timestamp] = []
    for ts in flags[flags].index:
        if not picked or (ts - picked[-1]).days > days * 7 / 5:
            picked.append(ts)
    return picked


def _row(event_type, instrument_id, scope, date, magnitude, surprise, title, source, approx=0, meta=None):
    return (_id(event_type, instrument_id, date.date()), event_type, instrument_id, scope, date.date().isoformat(),
            None if magnitude is None else float(magnitude), None if surprise is None else float(surprise),
            title, source, approx, db.dumps(meta) if meta else None)


def _save(records: list[tuple]) -> int:
    db.executemany(
        """INSERT OR REPLACE INTO events(id,type,instrument_id,scope,date,magnitude,surprise,title,source,approx_date,meta)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        records,
    )
    return len(records)


# ── Market shocks from prices ────────────────────────────────────────────────

def _zscore_moves(series: pd.Series, window: int, *, use_diff: bool = False) -> pd.Series:
    series = series.dropna()
    move = series.diff(window) if use_diff else series.pct_change(window, fill_method=None)
    sigma = move.rolling(250, min_periods=120).std().shift(1)
    return move / sigma


def detect_market_shocks() -> int:
    closes = data.closes()
    if closes.empty:
        return 0
    records: list[tuple] = []
    specs = [
        ("index:spx", 5, False, None, "equity_selloff", "S&P 500"),
        ("commodity:wti", 5, False, "oil_shock_up", "oil_shock_down", "WTI crude"),
        ("index:tnx", 5, True, "yield_spike", "yield_drop", "10Y yield"),
        ("index:dxy", 5, False, "dollar_surge", "dollar_slump", "US dollar"),
        ("crypto:btc", 3, False, "crypto_surge", "crypto_crash", "Bitcoin"),
    ]
    for instrument_id, window, use_diff, up_type, down_type, name in specs:
        if instrument_id not in closes:
            continue
        z = _zscore_moves(closes[instrument_id], window, use_diff=use_diff)
        for event_type, flags in ((up_type, z > SIGMA), (down_type, z < -SIGMA)):
            if not event_type:
                continue
            for ts in _cooldown(flags):
                records.append(_row(event_type, None, "macro", ts, z[ts], None,
                                    f"{name} {window}d move {z[ts]:+.1f}σ", "prices"))
    if "index:vix" in closes:
        vix = closes["index:vix"].dropna()
        ratio = vix / vix.rolling(20).mean().shift(1)
        for ts in _cooldown((ratio > 1.4) & (vix > 20)):
            records.append(_row("vix_spike", None, "macro", ts, vix[ts], ratio[ts],
                                f"VIX {vix[ts]:.1f} ({(ratio[ts] - 1) * 100:+.0f}% vs 20d avg)", "prices"))
    hy = data.macro("BAMLH0A0HYM2")
    if not hy.empty:
        calendar = _calendar()
        z = _zscore_moves(hy, 10, use_diff=True)
        for ts in _cooldown(z > SIGMA, 20):
            when = _snap(calendar, ts + pd.Timedelta(days=1))
            if when is not None:
                records.append(_row("credit_stress", None, "macro", when, hy[ts], z[ts],
                                    f"HY spread {hy[ts]:.2f}% (10d widening {z[ts]:+.1f}σ)", "FRED"))
    return _save(records)


# ── Fed decisions and macro releases (FRED) ─────────────────────────────────

def detect_macro_events() -> int:
    calendar = _calendar()
    if calendar.empty:
        return 0
    records: list[tuple] = []
    target = data.macro("DFEDTARU")
    if not target.empty:
        change = target.diff()
        for ts, delta in change[change.abs() > 0].items():
            # FRED records the effective date (day after the FOMC announcement).
            announced = _snap(calendar, ts - pd.tseries.offsets.BDay(1))
            if announced is None:
                continue
            kind = "rate_hike" if delta > 0 else "rate_cut"
            records.append(_row(kind, None, "macro", announced, delta * 100, None,
                                f"Fed {'hikes' if delta > 0 else 'cuts'} {abs(delta) * 100:.0f}bp to {target[ts]:.2f}%", "FRED"))

    def monthly_surprise(series_id: str, up: str, down: str, release_lag_days: int, unit: str, pct: bool) -> None:
        series = data.macro(series_id)
        if len(series) < 30:
            return
        change = (series.pct_change(fill_method=None) * 100) if pct else series.diff()
        z = (change - change.rolling(24, min_periods=12).mean().shift(1)) / change.rolling(24, min_periods=12).std().shift(1)
        for ts, value in z.dropna().items():
            if abs(value) < 1.0:
                continue
            released = _snap(calendar, ts + pd.DateOffset(months=1) + pd.Timedelta(days=release_lag_days))
            if released is None:
                continue
            kind = up if value > 0 else down
            records.append(_row(kind, None, "macro", released, change[ts], value,
                                f"{series_id} {ts:%b %Y}: {change[ts]:+.2f}{unit} ({value:+.1f}σ vs trend)",
                                "FRED", approx=1, meta={"observation": ts.date().isoformat(), "revised_data": True}))

    monthly_surprise("CPIAUCSL", "inflation_hot", "inflation_cool", 11, "% m/m", True)
    monthly_surprise("PAYEMS", "jobs_strong", "jobs_weak", 4, "k", False)
    return _save(records)


# ── Earnings (yfinance) ──────────────────────────────────────────────────────

def detect_earnings(instruments: list[universe.Instrument] | None = None, progress=None) -> int:
    calendar = _calendar()
    if calendar.empty:
        return 0
    instruments = instruments or [item for item in universe.INSTRUMENTS if item.asset_class == "stock"]
    records: list[tuple] = []
    for item in instruments:
        if progress:
            progress(f"earnings {item.symbol}")
        try:
            frame = yf.Ticker(item.provider_symbol).get_earnings_dates(limit=60)
        except Exception as exc:
            db.log("warn", "earnings", f"{item.symbol}: {exc}")
            continue
        if frame is None or frame.empty:
            continue
        for ts, row in frame.iterrows():
            surprise = row.get("Surprise(%)")
            if surprise is None or pd.isna(surprise):
                continue
            stamp = pd.Timestamp(ts)
            local = stamp.tz_convert("America/New_York") if stamp.tzinfo else stamp
            # Before the open: the market reacts the same day. After the open: next session.
            react = local.normalize().tz_localize(None)
            if local.time() >= dtime(9, 30):
                react = react + pd.Timedelta(days=1)
            when = _snap(calendar, react)
            if when is None:
                continue
            surprise = float(surprise)
            if surprise > 2:
                kind = "earnings_beat"
            elif surprise < -2:
                kind = "earnings_miss"
            else:
                continue
            records.append(_row(kind, item.id, "asset", when, row.get("Reported EPS"), surprise,
                                f"{item.symbol} EPS {row.get('Reported EPS')} vs est {row.get('EPS Estimate')} ({surprise:+.1f}%)",
                                "yfinance"))
    return _save(records)


# ── Geopolitics (GDELT theme spikes) ─────────────────────────────────────────

THEME_EVENTS = {
    "global_conflict": "geopolitical_escalation",
    "mideast_conflict": "mideast_escalation",
    "russia_ukraine_conflict": "russia_ukraine_escalation",
    "us_china_conflict": "us_china_tension",
    "sanctions": "sanctions_wave",
    "protest": "unrest_spike",
}


def detect_theme_events() -> int:
    calendar = _calendar()
    if calendar.empty:
        return 0
    records: list[tuple] = []
    for theme, event_type in THEME_EVENTS.items():
        share = data.theme_share(theme)
        if len(share) < 60:
            continue
        log_share = np.log(share.clip(lower=1e-9))
        z = (log_share - log_share.rolling(90, min_periods=45).mean().shift(1)) / log_share.rolling(90, min_periods=45).std().shift(1)
        for ts in _cooldown(z > SIGMA, 15):
            when = _snap(calendar, ts + pd.Timedelta(days=1))  # GDELT day = articles published that day
            if when is not None:
                records.append(_row(event_type, None, "global", when, share[ts], z[ts],
                                    f"{theme.replace('_', ' ')} coverage {z[ts]:+.1f}σ above 90d norm", "GDELT"))
    return _save(records)


def update_events(progress=None, *, earnings: bool = True) -> dict:
    data.invalidate()
    counts = {
        "market": detect_market_shocks(),
        "macro": detect_macro_events(),
        "themes": detect_theme_events(),
    }
    if earnings:
        counts["earnings"] = detect_earnings(progress=progress)
    data.invalidate()
    return counts
