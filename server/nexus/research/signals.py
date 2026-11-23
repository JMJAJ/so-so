"""Quant signals and the per-asset-class forecast model.

The same `panel()` builds training rows (backtest) and today's row (live), so the
live forecast is computed exactly the way it was validated. Every signal value at
date t is point-in-time.

Signals (positive = bullish), each standardised per instrument with an expanding
window:
  momentum   12-1 month return
  trend      distance from 200-day average
  reversal   minus 5-day return (short-term mean reversion)
  rsi        minus (RSI-14 − 50)
  analog     mean forward return of the 20 most similar past states, ÷ expected vol
  event      measured historical edge of events that just happened, ÷ expected vol
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .. import data, db, universe
from ..taxonomy import EVENT_TYPES
from . import analogs
from .features import abnormal_forward, asset_features

SIGNALS = ["momentum", "trend", "reversal", "rsi", "analog", "event"]
HORIZON = 20
EVENT_WINDOW = 5
SHRINK = 10


def _expanding_z(series: pd.Series) -> pd.Series:
    mean = series.expanding(min_periods=250).mean()
    std = series.expanding(min_periods=250).std()
    return ((series - mean) / std).clip(-4, 4)


class EventSignal:
    """Point-in-time event edge: for each event type, the average abnormal return of
    *earlier* occurrences whose outcome was already known at t (shrunk toward 0)."""

    def __init__(self, closes: pd.DataFrame, horizon: int):
        self.horizon = horizon
        self.calendar = closes.index
        bench = {item.id: item.benchmark_id for item in universe.INSTRUMENTS}
        self.abn = abnormal_forward(closes, horizon, bench)
        events = data.events_frame()
        self.events = events if not events.empty else pd.DataFrame(columns=["type", "instrument_id", "date"])
        self._pool_cache: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]] = {}

    def _positions(self, dates: pd.Series) -> np.ndarray:
        return self.calendar.searchsorted(pd.DatetimeIndex(dates))

    def series(self, instrument_id: str, sample_dates: pd.DatetimeIndex) -> pd.Series:
        item = universe.get(instrument_id)
        if item is None or self.events.empty or instrument_id not in self.abn:
            return pd.Series(0.0, index=sample_dates)
        sample_pos = self.calendar.searchsorted(sample_dates)
        total = np.zeros(len(sample_dates))
        for event_type, group in self.events.groupby("type"):
            scope = EVENT_TYPES.get(event_type, {}).get("scope", "macro")
            if scope == "asset":
                own = group[group["instrument_id"] == instrument_id]
                if own.empty:
                    continue
                key = (event_type, item.asset_class)
                if key not in self._pool_cache:
                    pool = group[group["instrument_id"].fillna("").str.startswith(f"{item.asset_class}:")]
                    pool_pos = self._positions(pool["date"])
                    columns = {c: i for i, c in enumerate(self.abn.columns)}
                    matrix = self.abn.to_numpy()
                    self._pool_cache[key] = (pool_pos, np.array([
                        matrix[p, columns[iid]] if iid in columns and p < len(matrix) else np.nan
                        for iid, p in zip(pool["instrument_id"], pool_pos)
                    ]))
                pos, outcomes = self._pool_cache[key]
                active_pos = np.sort(self._positions(own["date"]))
            else:
                pos = self._positions(group["date"].drop_duplicates())
                col = self.abn[instrument_id].to_numpy()
                outcomes = np.array([col[p] if p < len(col) else np.nan for p in pos])
                active_pos = np.sort(pos)
            known = pos + self.horizon
            order = np.argsort(known)
            known, outcomes = known[order], outcomes[order]
            mask = ~np.isnan(outcomes)
            known, outcomes = known[mask], outcomes[mask]
            if len(known) == 0:
                continue
            csum = np.concatenate([[0.0], np.cumsum(outcomes)])
            idx = np.searchsorted(known, sample_pos, side="left")  # outcomes known strictly before t
            n = idx.astype(float)
            mean = np.divide(csum[idx], n, out=np.zeros_like(n), where=n > 0)
            estimate = mean * n / (n + SHRINK)
            active = np.searchsorted(active_pos, sample_pos, side="right") - np.searchsorted(
                active_pos, sample_pos - EVENT_WINDOW, side="right")
            total += np.where(active > 0, estimate, 0.0)
        return pd.Series(total, index=sample_dates)


def panel(instrument_ids: list[str], sample_dates: pd.DatetimeIndex | None = None, *,
          horizon: int = HORIZON, step: int = 5, include_target: bool = True, progress=None,
          event_signal: EventSignal | None = None) -> pd.DataFrame:
    """Rows = (date, instrument). Columns = SIGNALS + y (forward return) + vol + asset_class."""
    closes = data.closes()
    if closes.empty:
        return pd.DataFrame()
    event_signal = event_signal or EventSignal(closes, horizon)
    grid = closes.index[::step]  # shared sampling grid keeps cross-sections aligned
    frames = []
    for instrument_id in instrument_ids:
        if instrument_id not in closes:
            continue
        if progress:
            progress(f"signals {instrument_id}")
        close = closes[instrument_id].dropna()
        if len(close) < 300:
            continue
        feats = asset_features(close)
        raw = pd.DataFrame({
            "momentum": feats["mom_12_1"],
            "trend": feats["dist_sma200"],
            "reversal": -feats["ret_5d"],
            "rsi": -(feats["rsi_14"] - 50),
        })
        z = raw.apply(_expanding_z)
        dates = sample_dates if sample_dates is not None else grid[grid >= close.index[260]]
        dates = dates.intersection(z.index)
        if len(dates) == 0:
            continue
        frame = z.loc[dates].copy()
        sigma_h = (feats["vol_20d"].loc[dates] * np.sqrt(horizon / 252)).replace(0, np.nan)
        frame["analog"] = (analogs.mean_forward_series(instrument_id, dates, horizon) / sigma_h).clip(-4, 4)
        frame["event"] = (event_signal.series(instrument_id, dates) / sigma_h).clip(-4, 4)
        frame["vol"] = feats["vol_20d"].loc[dates]
        if include_target:
            frame["y"] = (close.shift(-horizon) / close - 1).loc[dates]
        frame["instrument_id"] = instrument_id
        frame["asset_class"] = universe.get(instrument_id).asset_class
        frames.append(frame.reset_index(names="date"))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out[["analog", "event"]] = out[["analog", "event"]].fillna(0.0)
    return out


# ── Model (fit by backtest.py, applied here) ────────────────────────────────

def load_model(asset_class: str) -> dict | None:
    row = db.one("SELECT payload FROM models WHERE asset_class=?", (asset_class,))
    return db.loads(row["payload"]) if row else None


def apply_model(model: dict, row: pd.Series) -> dict:
    coefs = model["coefficients"]
    contributions = {name: float(coefs.get(name, 0.0) * (row.get(name) or 0.0)) for name in SIGNALS if name in coefs}
    expected = float(model["intercept"]) + sum(contributions.values()) if model.get("has_edge") else float(model["intercept"])
    sigma = float(row["vol"] * np.sqrt(model["horizon"] / 252)) if row.get("vol") and not pd.isna(row["vol"]) else None
    score = expected / sigma if sigma else 0.0
    if model.get("has_edge") and model.get("calibration"):
        calib = model["calibration"]
        prob_up = float(1 / (1 + np.exp(-(calib["a"] + calib["b"] * score))))
    else:
        # No validated edge: the honest probability is the historical base rate.
        prob_up = float(model.get("base_up_rate") or 0.5)
    return {
        "expected_return": expected,
        "sigma": sigma,
        "score": score,
        "prob_up": prob_up,
        "prob_naive": 0.5 * (1 + math.erf(score / math.sqrt(2))),  # standard normal CDF
        "contributions": contributions,
    }


def predict(instrument_ids: list[str] | None = None, *, progress=None) -> list[dict]:
    """Today's forecast for every tradable instrument, using each asset class's model."""
    closes = data.closes()
    if closes.empty:
        return []
    ids = instrument_ids or [item.id for item in universe.tradable()]
    last_date = closes.index[-1]
    event_signal = EventSignal(closes, HORIZON)
    rows = []
    for instrument_id in ids:
        if instrument_id not in closes:
            continue
        close = closes[instrument_id].dropna()
        if close.empty:
            continue
        if progress:
            progress(f"forecast {instrument_id}")
        frame = panel([instrument_id], pd.DatetimeIndex([close.index[-1]]), include_target=False,
                      event_signal=event_signal)
        if frame.empty:
            continue
        row = frame.iloc[0]
        item = universe.get(instrument_id)
        model = load_model(item.asset_class)
        forecast = apply_model(model, row) if model else {
            "expected_return": 0.0, "sigma": None, "score": 0.0, "prob_up": 0.5, "prob_naive": 0.5, "contributions": {}}
        stale_days = int((last_date - close.index[-1]).days)
        rows.append({
            "instrument_id": instrument_id,
            "symbol": item.symbol,
            "name": item.name,
            "asset_class": item.asset_class,
            "sector": item.sector,
            "as_of": close.index[-1].date().isoformat(),
            "stale_days": stale_days,
            "price": float(close.iloc[-1]),
            "signals": {name: _round(row.get(name)) for name in SIGNALS},
            "vol_20d": _round(row.get("vol")),
            "model_has_edge": bool(model and model.get("has_edge")),
            **{key: (_round(value) if not isinstance(value, dict) else {k: _round(v) for k, v in value.items()})
               for key, value in forecast.items()},
        })
    return rows


def _round(value, digits: int = 4):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(number) else round(number, digits)
