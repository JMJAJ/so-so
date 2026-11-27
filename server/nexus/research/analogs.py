"""Historical analogs: past dates whose asset + market state most resembles today,
and what the asset did over the following weeks.

State vector = the asset's own momentum/volatility/trend plus market regime.
Each feature is standardised with an expanding (past-only) mean/std, so a backtest
calling `find(as_of=t)` never peeks past t. Candidates must end their forward
window before `as_of` and be at least `spacing` sessions apart.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import data, universe
from .features import asset_features, regime_frame

ASSET_COLS = ["ret_5d", "ret_20d", "ret_60d", "vol_ratio", "rsi_14", "dist_sma200", "dist_high_252"]
REGIME_COLS = ["vix_pct_1y", "spy_ret_60d", "curve", "us10y_chg_60d", "dxy_ret_60d", "hy_spread", "conflict_z"]
FORWARD = 40


def _state(instrument_id: str, features: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.Series]:
    """`features`: `asset_features` of this instrument's closes, when the caller already has them."""
    return data._cached(("analog_state", instrument_id), lambda: _build_state(instrument_id, features))


def _build_state(instrument_id: str, features: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.Series]:
    closes = data.closes()
    close = closes[instrument_id].dropna()
    feats = (features if features is not None else asset_features(close))[ASSET_COLS]
    regime = regime_frame()
    cols = [c for c in REGIME_COLS if c in regime and regime[c].notna().sum() > 250]
    state = feats.join(regime[cols], how="left")
    # Expanding z-score: uses only information available at each date.
    mean = state.expanding(min_periods=250).mean()
    std = state.expanding(min_periods=250).std()
    z = ((state - mean) / std).clip(-4, 4)
    usable = [c for c in z.columns if z[c].notna().sum() > 250]
    return z[usable], close


def find(instrument_id: str, k: int = 20, as_of: pd.Timestamp | None = None, spacing: int = 10,
         horizon: int = 20, with_paths: bool = True) -> dict | None:
    item = universe.get(instrument_id)
    closes = data.closes()
    if not item or closes.empty or instrument_id not in closes:
        return None
    z, close = _state(instrument_id)
    z = z.dropna()
    if as_of is not None:
        z = z[z.index <= as_of]
    if len(z) < 400:
        return None
    today = z.iloc[-1]
    today_date = z.index[-1]
    positions = close.index.get_indexer(z.index)
    last_pos = close.index.get_loc(today_date)
    # Candidates whose forward window closes before today (no overlap with the present).
    candidates = z[(positions + FORWARD) < last_pos]
    candidates = candidates.iloc[:-1] if len(candidates) else candidates
    if len(candidates) < 50:
        return None
    distance = np.sqrt(((candidates - today) ** 2).mean(axis=1))
    chosen: list[pd.Timestamp] = []
    for ts in distance.sort_values().index:
        pos = close.index.get_loc(ts)
        if all(abs(pos - close.index.get_loc(other)) >= spacing for other in chosen):
            chosen.append(ts)
        if len(chosen) >= k:
            break

    bench_id = item.benchmark_id
    bench = closes[bench_id] if bench_id and bench_id in closes else None
    paths, finals, excess = [], [], []
    for ts in chosen:
        pos = close.index.get_loc(ts)
        window = close.iloc[pos:pos + FORWARD + 1]
        path = (window / window.iloc[0] - 1).to_numpy()
        paths.append(path)
        finals.append(path[min(horizon, len(path) - 1)])
        if bench is not None and ts in bench.index:
            b_window = bench.reindex(window.index)
            excess.append(finals[-1] - float(b_window.iloc[min(horizon, len(b_window) - 1)] / b_window.iloc[0] - 1))
    finals_arr = np.array(finals)
    result = {
        "instrument_id": instrument_id,
        "as_of": today_date.date().isoformat(),
        "k": len(chosen),
        "horizon": horizon,
        "features": list(z.columns),
        "today_state": {c: round(float(today[c]), 2) for c in z.columns},
        "mean_return": float(finals_arr.mean()),
        "median_return": float(np.median(finals_arr)),
        "hit_rate": float((finals_arr > 0).mean()),
        "mean_excess": float(np.mean(excess)) if excess else None,
        "dispersion": float(finals_arr.std()),
        "analogs": [
            {"date": ts.date().isoformat(), "distance": round(float(distance[ts]), 3), "fwd_return": float(finals[i])}
            for i, ts in enumerate(chosen)
        ],
    }
    if with_paths and paths:
        length = min(len(p) for p in paths)
        matrix = np.vstack([p[:length] for p in paths])
        result["fan"] = [
            {"day": d, **{f"p{q}": float(np.percentile(matrix[:, d], q)) for q in (10, 25, 50, 75, 90)}}
            for d in range(length)
        ]
    return result


def _pick(order: np.ndarray, positions: np.ndarray, k: int, spacing: int) -> list[int]:
    chosen: list[int] = []
    for idx in order:
        pos = positions[idx]
        if all(abs(pos - positions[other]) >= spacing for other in chosen):
            chosen.append(int(idx))
            if len(chosen) >= k:
                break
    return chosen


def mean_forward_series(instrument_id: str, sample_dates: pd.DatetimeIndex, horizon: int = 20,
                        k: int = 20, spacing: int = 10, features: pd.DataFrame | None = None) -> pd.Series:
    """Point-in-time analog forecast (mean forward return of the k nearest past states)
    for many dates at once. Used by the walk-forward backtest and live signals."""
    z, close = _state(instrument_id, features)
    z = z.dropna()
    if len(z) < 400:
        return pd.Series(dtype=float)
    matrix = z.to_numpy()
    positions = close.index.get_indexer(z.index)
    close_np = close.to_numpy()
    fwd = np.full(len(z), np.nan)
    valid = positions + horizon < len(close_np)
    fwd[valid] = close_np[positions[valid] + horizon] / close_np[positions[valid]] - 1
    out = {}
    for ts in sample_dates:
        if ts not in z.index:
            continue
        row = z.index.get_loc(ts)
        cutoff = positions[row] - FORWARD
        eligible = np.nonzero(positions[:row] < cutoff)[0]
        if len(eligible) < 250:
            continue
        dist = np.sqrt(((matrix[eligible] - matrix[row]) ** 2).mean(axis=1))
        order = eligible[np.argsort(dist)[: k * 6]]
        chosen = _pick(order, positions, k, spacing)
        values = fwd[chosen]
        values = values[~np.isnan(values)]
        if len(values) >= k // 2:
            out[ts] = float(values.mean())
    return pd.Series(out, dtype=float)
