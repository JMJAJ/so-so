"""Walk-forward validation of the signal model, per asset class.

For each test year Y: fit a ridge regression on rows whose outcome was known before
Y started (purged by the horizon), predict Y, move on. Only out-of-sample
predictions are scored. The final model (fit on everything) is stored with a
`has_edge` flag. If the walk-forward IC isn't positive and significant, live
forecasts fall back to the drift-only intercept and the analyst is told that the
quant model has no measured edge for that asset class.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .. import db, universe
from .signals import HORIZON, SIGNALS, panel

RIDGE = 5.0
MIN_TRAIN_YEARS = 3


def _ridge(x: np.ndarray, y: np.ndarray, lam: float) -> tuple[float, np.ndarray]:
    # Standardise columns so the penalty treats sparse signals (e.g. events) like dense ones.
    x_mean, y_mean = x.mean(axis=0), y.mean()
    x_std = x.std(axis=0)
    x_std[x_std == 0] = 1.0
    xs, yc = (x - x_mean) / x_std, y - y_mean
    coef = np.linalg.solve(xs.T @ xs + lam * len(y) / 100 * np.eye(x.shape[1]), xs.T @ yc) / x_std
    return float(y_mean - x_mean @ coef), coef


def _ic(pred: np.ndarray, y: np.ndarray) -> tuple[float, float, int]:
    n = len(y)
    if n < 20:
        return 0.0, 0.0, n
    ic = float(spearmanr(pred, y).statistic)
    if np.isnan(ic):
        return 0.0, 0.0, n
    t = ic * np.sqrt(max(n - 2, 1) / max(1 - ic ** 2, 1e-9))
    return ic, float(t), n


def _select(train: pd.DataFrame, horizon: int, min_t: float = 2.0) -> list[str]:
    """Signals whose IC in the training window alone is significant (no look-ahead)."""
    sparse = _non_overlapping(train, horizon)
    chosen = []
    for name in SIGNALS:
        _, t, _ = _ic(sparse[name].fillna(0.0).to_numpy(), sparse["y"].to_numpy())
        if abs(t) >= min_t:
            chosen.append(name)
    return chosen


def _non_overlapping(frame: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Keep one row per instrument every `horizon` sessions so t-stats aren't inflated."""
    dates = np.sort(frame["date"].unique())
    keep = set(dates[::max(horizon // 5, 1)])
    return frame[frame["date"].isin(keep)]


def _logistic(score: np.ndarray, up: np.ndarray) -> dict:
    a, b = 0.0, 1.0
    for _ in range(200):  # Newton steps on a 2-parameter logistic regression
        p = 1 / (1 + np.exp(-(a + b * score)))
        w = p * (1 - p) + 1e-9
        grad = np.array([np.sum(up - p), np.sum((up - p) * score)])
        hess = np.array([[np.sum(w), np.sum(w * score)], [np.sum(w * score), np.sum(w * score * score)]])
        try:
            step = np.linalg.solve(hess + 1e-6 * np.eye(2), grad)
        except np.linalg.LinAlgError:
            break
        a, b = a + step[0], b + step[1]
        if np.abs(step).max() < 1e-8:
            break
    return {"a": float(a), "b": float(np.clip(b, 0.0, 6.0))}


CROSS_SECTIONAL = ("stock", "etf", "crypto")


def evaluate_class(frame: pd.DataFrame, asset_class: str, horizon: int) -> dict:
    """Score signals against `target`: raw forward return, or for classes with a real
    cross-section, return relative to the same-date class average (which asset beats
    its peers, the question a stock picker actually asks)."""
    frame = frame.dropna(subset=["y", "vol"]).copy()
    frame["year"] = pd.to_datetime(frame["date"]).dt.year
    base_mean = float(frame["y"].mean()) if len(frame) else 0.0
    relative = asset_class in CROSS_SECTIONAL
    if relative:
        frame["y_raw"] = frame["y"]
        frame["y"] = frame["y"] - frame.groupby("date")["y"].transform("mean")
    y_all = frame["y"].to_numpy()
    result: dict = {"asset_class": asset_class, "horizon": horizon, "rows": int(len(frame)), "signals": {},
                    "target": "relative to class average" if relative else "raw return",
                    "base_up_rate": float(((frame["y_raw"] if relative else frame["y"]) > 0).mean()) if len(frame) else 0.5,
                    "base_mean": base_mean}
    if len(frame) < 300:
        result["has_edge"] = False
        result["reason"] = "not enough history"
        return result

    sparse = _non_overlapping(frame, horizon)
    for name in SIGNALS:
        values = sparse[name].fillna(0.0).to_numpy()
        ys = sparse["y"].to_numpy()
        ic, t, n = _ic(values, ys)
        strong_long, strong_short = ys[values > 1], ys[values < -1]
        directional = np.abs(values) > 0.5
        result["signals"][name] = {
            "ic": ic, "t_stat": t, "n": n,
            "hit_rate": float((np.sign(values[directional]) == np.sign(ys[directional])).mean()) if directional.any() else None,
            "long_short": float(strong_long.mean() - strong_short.mean()) if len(strong_long) > 5 and len(strong_short) > 5 else None,
        }

    years = sorted(frame["year"].unique())
    oos = []
    selections: dict[int, list[str]] = {}
    for test_year in years[MIN_TRAIN_YEARS:]:
        test_start = pd.Timestamp(year=int(test_year), month=1, day=1)
        purge = test_start - pd.Timedelta(days=int(horizon * 7 / 5) + 2)
        train = frame[pd.to_datetime(frame["date"]) < purge]
        test = frame[frame["year"] == test_year]
        if len(train) < 200 or test.empty:
            continue
        chosen = _select(train, horizon)
        if chosen:
            intercept, coef = _ridge(train[chosen].fillna(0.0).to_numpy(), train["y"].to_numpy(), RIDGE)
            pred = intercept + test[chosen].fillna(0.0).to_numpy() @ coef
        else:
            pred = np.full(len(test), float(train["y"].mean()))
        oos.append(test.assign(pred=pred))
        selections[int(test_year)] = chosen
    if not oos:
        result["has_edge"] = False
        result["reason"] = "not enough years for walk-forward"
        return result
    oos_frame = pd.concat(oos)
    sparse_oos = _non_overlapping(oos_frame, horizon)
    ic, t, n = _ic(sparse_oos["pred"].to_numpy(), sparse_oos["y"].to_numpy())
    pred, ys = sparse_oos["pred"].to_numpy(), sparse_oos["y"].to_numpy()
    q_hi, q_lo = np.quantile(pred, 0.8), np.quantile(pred, 0.2)
    sigma = (sparse_oos["vol"] * np.sqrt(horizon / 252)).replace(0, np.nan).to_numpy()
    score = np.nan_to_num(pred / sigma)
    by_year = {
        int(year): _ic(group["pred"].to_numpy(), group["y"].to_numpy())[0]
        for year, group in sparse_oos.groupby("year") if len(group) >= 20
    }
    result["walk_forward"] = {
        "ic": ic, "t_stat": t, "n": n,
        "hit_rate": float((np.sign(pred) == np.sign(ys)).mean()),
        "top_quintile": float(ys[pred >= q_hi].mean()),
        "bottom_quintile": float(ys[pred <= q_lo].mean()),
        "long_short": float(ys[pred >= q_hi].mean() - ys[pred <= q_lo].mean()),
        "unconditional": float(ys.mean()),
        "ic_by_year": by_year,
        "period": [str(oos_frame["date"].min())[:10], str(oos_frame["date"].max())[:10]],
    }
    up = (sparse_oos["y_raw"] if relative else sparse_oos["y"]).to_numpy() > 0
    # Live forecasts add the class drift back, so calibrate on (drift + relative prediction).
    result["calibration"] = _logistic(np.nan_to_num((pred + (base_mean if relative else 0.0)) / sigma), up.astype(float))
    final = _select(frame, horizon)
    result["selected_signals"] = final
    result["selection_by_year"] = selections
    if final:
        intercept, coef = _ridge(frame[final].fillna(0.0).to_numpy(), y_all, RIDGE)
        result["coefficients"] = {name: float(value) for name, value in zip(final, coef)}
    else:
        intercept = float(y_all.mean())
        result["coefficients"] = {}
    result["intercept"] = intercept + (base_mean if relative else 0.0)
    result["has_edge"] = bool(ic > 0.02 and t > 2.0)
    if not result["has_edge"]:
        result["reason"] = f"walk-forward IC {ic:+.3f} (t={t:.1f}) is not a reliable edge"
    return result


def run(*, horizon: int = HORIZON, step: int = 5, years: int = 10, progress=None) -> dict:
    ids = [item.id for item in universe.tradable()]
    frame = panel(ids, horizon=horizon, step=step, progress=progress)
    if frame.empty:
        return {"classes": {}}
    cutoff = pd.Timestamp.today() - pd.Timedelta(days=365 * years)
    frame = frame[pd.to_datetime(frame["date"]) >= cutoff]
    computed_at = db.now_iso()
    results = {}
    for asset_class, group in frame.groupby("asset_class"):
        if progress:
            progress(f"backtest {asset_class}")
        result = evaluate_class(group, asset_class, horizon)
        results[asset_class] = result
        payload = {key: result.get(key) for key in (
            "asset_class", "horizon", "rows", "has_edge", "reason", "intercept", "coefficients",
            "calibration", "walk_forward", "signals", "base_up_rate", "base_mean", "target", "selected_signals")}
        if payload["intercept"] is None:
            payload["intercept"] = float(group["y"].dropna().mean()) if group["y"].notna().any() else 0.0
            payload["coefficients"] = {}
        db.execute(
            """INSERT INTO models(asset_class,horizon,payload,computed_at) VALUES(?,?,?,?)
               ON CONFLICT(asset_class) DO UPDATE SET horizon=excluded.horizon, payload=excluded.payload,
               computed_at=excluded.computed_at""",
            (asset_class, horizon, db.dumps(payload), computed_at),
        )
        wf = result.get("walk_forward") or {}
        records = [(name, asset_class, horizon, stats["n"], stats["ic"], stats["hit_rate"], None,
                    stats["long_short"], stats["t_stat"], None, None, computed_at)
                   for name, stats in result["signals"].items()]
        if wf:
            records.append(("combined_oos", asset_class, horizon, wf["n"], wf["ic"], wf["hit_rate"], None,
                            wf["long_short"], wf["t_stat"], wf["period"][0], wf["period"][1], computed_at))
        db.executemany(
            """INSERT OR REPLACE INTO signal_stats(signal,asset_class,horizon,n,ic,hit_rate,mean_excess,long_short,t_stat,
               period_start,period_end,computed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            records,
        )
    return {"classes": results}


def summary() -> list[dict]:
    out = []
    for row in db.rows("SELECT asset_class, payload, computed_at FROM models ORDER BY asset_class"):
        payload = db.loads(row["payload"], {})
        out.append({
            "asset_class": row["asset_class"], "computed_at": row["computed_at"],
            "has_edge": payload.get("has_edge"), "reason": payload.get("reason"),
            "walk_forward": payload.get("walk_forward"), "signals": payload.get("signals"),
            "coefficients": payload.get("coefficients"),
        })
    return out
