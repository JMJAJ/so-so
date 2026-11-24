"""Shock reactions: what an asset did after days like today.

Live news shows up first as a price shock. This module measures, on the asset's own
history, what followed past shocks of the same size and direction: did the move keep
going (follow it) or give back (fade it)? It is the evidence behind event-driven trades.

  shock     a session whose return is >= `SIGMA` of the asset's trailing 60-session daily
            volatility (the σ window ends the day before, so it is known at t). Shocks
            within `COOLDOWN` sessions of a previous one are dropped: a crash week is one event.
  reaction  forward return from the shock day's close, 1-10 sessions out, minus the asset's
            unconditional mean over the same horizon; per asset, and pooled per asset class with
            one observation per date. Benjamini-Hochberg across the whole universe, split-half
            stability and n >= RELIABLE_N, as for event studies.
  bracket   the same stop/target replayed only from past shock days (probability.py),
            so the trade's base rate is conditional on the situation it is entered in.

Point-in-time: σ at t uses returns up to t-1; the shock uses the close of t.
"""

from __future__ import annotations

import threading

import numpy as np
import pandas as pd

from .. import data, universe
from . import event_study

SIGMA = 2.0
VOL_WINDOW = 60
COOLDOWN = 3
HORIZONS = (1, 3, 5, 10)
RELIABLE_N = 15
FDR_Q = 0.10
HISTORY_DAYS = 365 * 10


def zscores(close: pd.Series) -> pd.Series:
    """Daily return divided by the trailing σ known the day before."""
    ret = close.pct_change(fill_method=None)
    sigma = ret.rolling(VOL_WINDOW, min_periods=40).std().shift(1)
    return ret / sigma


def shock_days(close: pd.Series, side: str, threshold: float = SIGMA) -> pd.DatetimeIndex:
    """Dates of `side` ('up'/'down') shocks of at least `threshold` σ, de-clustered."""
    z = zscores(close)
    flags = z >= threshold if side == "up" else z <= -threshold
    out, last = [], None
    positions = {d: i for i, d in enumerate(close.index)}
    for day in close.index[flags.fillna(False).to_numpy()]:
        i = positions[day]
        if last is None or i - last > COOLDOWN:
            out.append(day)
            last = i
    return pd.DatetimeIndex(out)


def _history(instrument_id: str) -> pd.Series:
    start = (pd.Timestamp.today() - pd.Timedelta(days=HISTORY_DAYS)).date().isoformat()
    frame = data.ohlcv(instrument_id, start)
    return frame["close"].dropna() if not frame.empty else pd.Series(dtype=float)


def current_shock(instrument_id: str, quote: dict | None = None) -> dict | None:
    """Today's move in σ: the live quote when it is fresh, else the last stored session.
    Also checks the last two stored sessions, because a shock yesterday is still tradable."""
    close = _history(instrument_id)
    if len(close) < VOL_WINDOW + 5:
        return None
    ret = close.pct_change(fill_method=None)
    sigma = float(ret.tail(VOL_WINDOW).std())
    if not sigma or np.isnan(sigma):
        return None
    live = quote.get("change_pct") if quote else None
    candidates = []
    if live is not None:
        candidates.append({"date": "live", "move": live / 100, "z": (live / 100) / sigma, "source": "live quote"})
    z_hist = zscores(close)
    for day in close.index[-2:]:
        z = z_hist.get(day)
        if z is not None and not np.isnan(z):
            candidates.append({"date": day.date().isoformat(), "move": float(ret[day]), "z": float(z),
                               "source": "daily bar"})
    if not candidates:
        return None
    best = max(candidates, key=lambda c: abs(c["z"]))
    warnings = []
    if quote and quote.get("price") and len(close):
        gap = quote["price"] / float(close.iloc[-1]) - 1
        if live is not None and abs(gap - live / 100) > 3 * sigma and abs(gap) > 3 * sigma:
            warnings.append(f"Live price {quote['price']:.4g} is {gap:+.1%} from the last stored close "
                            f"{float(close.iloc[-1]):.4g} but the quote says {live:+.1f}% today: check the bars "
                            "for a bad print before trading on this move.")
    big_days = [float(x) for x in z_hist.tail(3).dropna() if abs(x) >= 4]
    if len(big_days) >= 2 and np.sign(big_days[0]) != np.sign(big_days[-1]):
        warnings.append("Back-to-back opposite moves of 4σ+ in the last three sessions: likely a bad bar or a "
                        "split. Confirm against the chart before trading.")
    return {"z": round(best["z"], 2), "move": round(best["move"], 4), "date": best["date"],
            "source": best["source"], "daily_sigma": round(sigma, 4),
            "side": "up" if best["z"] > 0 else "down", "is_shock": abs(best["z"]) >= SIGMA,
            "warnings": warnings}


def _forward(close: pd.Series, horizon: int) -> pd.Series:
    return close.shift(-horizon) / close - 1


def _row(stats: dict, q_value: float, side: str, n_key: str = "n") -> dict:
    # A positive edge after an up-shock is continuation; after a down-shock it is a rebound.
    follows = (stats["edge"] > 0) == (side == "up")
    return {
        "n": stats["n"], **({"n_dates": stats["n_dates"]} if "n_dates" in stats else {}),
        "mean": round(stats["mean"], 5), "edge": round(stats["edge"], 5), "hit_rate": round(stats["hit_rate"], 3),
        "t_stat": round(stats["t_stat"], 2), "q_value": round(q_value, 4), "stable": stats["stable"],
        "reliable": bool(q_value <= FDR_Q and stats["stable"] and stats[n_key] >= RELIABLE_N),
        "pattern": "continuation" if follows else "reversal",
    }


def _clustered(obs: pd.DataFrame) -> dict | None:
    """Pooled shocks of one asset class, one observation per date (the mean edge of every asset
    that shocked that day), so a market-wide crash counts once rather than 70 times."""
    if obs.empty:
        return None
    by_date = obs.groupby("date")["edge"].mean().sort_index()
    n_dates = len(by_date)
    if n_dates < RELIABLE_N:
        return None
    mean, sd = float(by_date.mean()), float(by_date.std(ddof=1))
    t_stat = mean / (sd / np.sqrt(n_dates)) if sd > 0 else 0.0
    half = n_dates // 2
    early, late = float(by_date.iloc[:half].mean()), float(by_date.iloc[half:].mean())
    return {"n": int(len(obs)), "n_dates": n_dates, "mean": float(obs["raw"].mean()), "edge": mean,
            "hit_rate": float((obs["raw"] > 0).mean()), "t_stat": float(t_stat),
            "p_value": event_study._t_two_sided(t_stat, max(n_dates - 1, 1)),
            "stable": bool(half >= 3 and mean != 0 and np.sign(early) == np.sign(mean) == np.sign(late))}


_table: dict = {"key": None, "value": None}
_table_lock = threading.Lock()


def table() -> dict:
    """Every tradable asset's shock reactions plus per-class pools, with Benjamini-Hochberg run
    across the whole universe (one family for assets, one for pools). Correcting one asset at a
    time would let roughly 10% of pure noise through across ~1,000 asset x side x horizon tests.
    Cached until a new bar arrives."""
    from .. import db

    last = db.one("SELECT MAX(date) d FROM bars")
    key = (db.DB_PATH, last["d"] if last else None, len(universe.INSTRUMENTS))
    with _table_lock:
        if _table["key"] == key and _table["value"] is not None:
            return _table["value"]
        tests, pooled_obs, counts = [], {}, {}
        for item in universe.INSTRUMENTS:
            if not item.tradable:
                continue
            close = _history(item.id)
            if len(close) < VOL_WINDOW + 60:
                continue
            fwd = {h: _forward(close, h) for h in HORIZONS}
            for side in ("up", "down"):
                dates = shock_days(close, side)
                counts[(item.id, side)] = len(dates)
                for h in HORIZONS:
                    sample = fwd[h].reindex(dates).dropna()
                    stats = event_study._stats(sample, fwd[h].dropna())
                    if stats:
                        tests.append((item.id, side, h, stats))
                    if len(sample):
                        pooled_obs.setdefault((item.asset_class, side, h), []).append(pd.DataFrame(
                            {"date": sample.index, "raw": sample.to_numpy(),
                             "edge": sample.to_numpy() - float(fwd[h].mean())}))
        assets: dict = {}
        q_assets = event_study.benjamini_hochberg([t[3]["p_value"] for t in tests])
        for (instrument_id, side, h, stats), q in zip(tests, q_assets):
            assets.setdefault((instrument_id, side), {})[h] = _row(stats, q, side)
        pool_tests = [(k, _clustered(pd.concat(v, ignore_index=True))) for k, v in pooled_obs.items()]
        pool_tests = [(k, s) for k, s in pool_tests if s]
        pools: dict = {}
        q_pools = event_study.benjamini_hochberg([s["p_value"] for _, s in pool_tests])
        for ((asset_class, side, h), stats), q in zip(pool_tests, q_pools):
            pools.setdefault((asset_class, side), {})[h] = _row(stats, q, side, n_key="n_dates")
        value = {"assets": assets, "pools": pools, "counts": counts,
                 "family": {"asset_tests": len(tests), "pool_tests": len(pool_tests)}}
        _table.update(key=key, value=value)
        return value


def _verdict(rows: dict, side: str, label: str) -> str | None:
    reliable = [h for h, r in rows.items() if r["reliable"]]
    if not reliable:
        return None
    best = max(reliable, key=lambda h: abs(rows[h]["t_stat"]))
    r = rows[best]
    return (f"{label}: {r['pattern']} after {side} shocks is reliable at {best} sessions (edge {r['edge']:+.2%}, "
            f"hit {r['hit_rate']:.0%}, t={r['t_stat']}, n={r['n']}, q={r['q_value']})")


def reaction(instrument_id: str, side: str, threshold: float = SIGMA) -> dict:
    """Follow-through vs reversal after past `side` shocks: this asset, and its asset class pooled.
    A custom threshold is exploratory: computed for this asset alone and never reliable."""
    item = universe.require(instrument_id)
    if threshold != SIGMA:
        close = _history(item.id)
        rows, dates = {}, pd.DatetimeIndex([])
        if len(close) > VOL_WINDOW:
            dates = shock_days(close, side, threshold)
            for h in HORIZONS:
                fwd = _forward(close, h)
                stats = event_study._stats(fwd.reindex(dates).dropna(), fwd.dropna())
                if stats:
                    rows[h] = {**_row(stats, 1.0, side), "reliable": False}
        return {"instrument_id": item.id, "symbol": item.symbol, "side": side, "threshold_sigma": threshold,
                "n_shocks": len(dates), "horizons": rows, "pooled": {}, "reliable_horizons": [],
                "pooled_reliable_horizons": [],
                "verdict": "exploratory threshold: shown for context, never counted as evidence"}
    data_table = table()
    own = data_table["assets"].get((item.id, side), {})
    pooled = data_table["pools"].get((item.asset_class, side), {})
    verdicts = [v for v in (_verdict(own, side, item.symbol), _verdict(pooled, side, f"all {item.asset_class}s"))
                if v]
    return {"instrument_id": item.id, "symbol": item.symbol, "side": side, "threshold_sigma": threshold,
            "n_shocks": data_table["counts"].get((item.id, side), 0),
            "horizons": own, "pooled": {"asset_class": item.asset_class, "horizons": pooled},
            "reliable_horizons": [h for h, r in own.items() if r["reliable"]],
            "pooled_reliable_horizons": [h for h, r in pooled.items() if r["reliable"]],
            "family": data_table["family"],
            "verdict": "; ".join(verdicts) if verdicts else
            "no reliable follow-through or reversal after shocks like this (this asset or its class): noise"}


def trade_direction(reaction_result: dict, horizon: int) -> tuple[str, dict, str] | None:
    """(direction, stats row, source) of a reliable reaction at the horizon nearest `horizon`:
    the asset's own when reliable, else its class pool unless the asset's own edge disagrees."""
    own = reaction_result.get("horizons") or {}
    pooled = (reaction_result.get("pooled") or {}).get("horizons") or {}
    for rows, source in ((own, "asset"), (pooled, "pool")):
        if not rows:
            continue
        h = min(rows, key=lambda k: abs(int(k) - horizon))
        row = rows[h]
        if not row["reliable"]:
            continue
        if source == "pool" and h in own and np.sign(own[h]["edge"]) != np.sign(row["edge"]):
            return None
        return ("long" if row["edge"] > 0 else "short"), {**row, "horizon": h}, source
    return None
