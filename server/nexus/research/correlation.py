"""Cross-asset co-movement and lead-lag links between drivers and an asset.

Lead-lag asks: does a change in driver X during week t predict the asset's return
over the following `horizon` sessions? Only links with |r| above a significance
threshold (≈ 2/√n_effective, non-overlapping samples) are reported.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import data, universe

DRIVERS = {
    "index:vix": ("VIX level change", "diff"),
    "index:tnx": ("10Y yield change", "diff"),
    "index:dxy": ("US dollar return", "pct"),
    "commodity:wti": ("Oil return", "pct"),
    "commodity:gold": ("Gold return", "pct"),
    "etf:spy": ("S&P 500 return", "pct"),
    "etf:hyg": ("High-yield bond return", "pct"),
    "crypto:btc": ("Bitcoin return", "pct"),
}
THEME_DRIVERS = {
    "global_conflict": "Armed-conflict news intensity",
    "mideast_conflict": "Middle East conflict news",
    "russia_ukraine_conflict": "Russia/Ukraine conflict news",
    "us_china_conflict": "US–China conflict news",
    "sanctions": "Sanctions news intensity",
}


def peers(instrument_id: str, window: int = 252, limit: int = 8) -> dict:
    closes = data.closes()
    if instrument_id not in closes:
        return {"positive": [], "negative": []}
    rets = closes.pct_change(fill_method=None).iloc[-window:]
    tradable = [item.id for item in universe.INSTRUMENTS if item.id in rets and item.id != instrument_id]
    corr = rets[tradable].corrwith(rets[instrument_id]).dropna()
    recent = closes.pct_change(fill_method=None).iloc[-60:][tradable].corrwith(rets[instrument_id].iloc[-60:]).dropna()

    def pack(ids):
        return [{"instrument_id": i, "symbol": universe.get(i).symbol, "corr_1y": round(float(corr[i]), 3),
                 "corr_60d": round(float(recent.get(i, np.nan)), 3) if i in recent else None} for i in ids]

    ordered = corr.sort_values()
    return {"positive": pack(ordered.index[::-1][:limit]), "negative": pack(ordered.index[:limit])}


def _driver_series(closes: pd.DataFrame) -> dict[str, tuple[str, pd.Series]]:
    drivers: dict[str, tuple[str, pd.Series]] = {}
    for key, (name, kind) in DRIVERS.items():
        if key in closes:
            series = closes[key]
            drivers[key] = (name, series.diff(5) if kind == "diff" else series.pct_change(5, fill_method=None))
    for theme, name in THEME_DRIVERS.items():
        share = data.theme_share(theme)
        if len(share) > 120:
            weekly = share.rolling(5, min_periods=3).mean()
            drivers[f"theme:{theme}"] = (name, np.log(weekly.clip(lower=1e-9)).diff(5).reindex(closes.index, method="ffill"))
    return drivers


def lead_lag(instrument_id: str, horizon: int = 20) -> list[dict]:
    closes = data.closes()
    if instrument_id not in closes:
        return []
    future = closes[instrument_id].shift(-horizon) / closes[instrument_id] - 1
    results = []
    for key, (name, series) in _driver_series(closes).items():
        if key == instrument_id:
            continue
        frame = pd.concat([series.rename("x"), future.rename("y")], axis=1).dropna()
        # Non-overlapping samples so the significance threshold is honest.
        frame = frame.iloc[::horizon]
        n = len(frame)
        if n < 30:
            continue
        r = float(frame["x"].corr(frame["y"]))
        threshold = 2 / np.sqrt(n)
        if abs(r) < threshold:
            continue
        current = series.dropna()
        latest = float(current.iloc[-1]) if len(current) else None
        z_now = float((current.iloc[-1] - current.mean()) / current.std()) if len(current) > 30 else None
        results.append({
            "driver": key, "name": name, "horizon": horizon, "corr": round(r, 3), "n": n,
            "threshold": round(float(threshold), 3), "latest_change": latest,
            "latest_z": round(z_now, 2) if z_now is not None else None,
            "implied_direction": (1 if r * (z_now or 0) > 0 else -1) if z_now and abs(z_now) > 1 else 0,
        })
    return sorted(results, key=lambda row: -abs(row["corr"]))


def matrix(instrument_ids: list[str], window: int = 120) -> dict:
    closes = data.closes()
    ids = [i for i in instrument_ids if i in closes]
    corr = closes[ids].pct_change(fill_method=None).iloc[-window:].corr()
    return {"ids": ids, "values": [[round(float(v), 3) for v in row] for row in corr.to_numpy()]}
