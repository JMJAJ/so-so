"""Event studies: what happened to each asset after each kind of event.

Entry is the close of the event's reaction session (see ingest/events.py), so the
numbers describe returns you could have captured after the news was known.
Measure: return minus benchmark for stocks/ETFs (vs SPY) and alt-coins (vs BTC);
raw return for FX, commodities, SPY and BTC. `edge` = event mean − the asset's
unconditional mean over the same period. Overlapping windows make t-stats
optimistic; treat |t| < 2 as noise.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as sstats

from .. import data, db, universe
from ..taxonomy import EVENT_TYPES, label
from .features import abnormal_forward

HORIZONS = (0, 5, 10, 20, 40)
MIN_N = 5


def _benchmarks() -> dict[str, str | None]:
    return {item.id: item.benchmark_id for item in universe.INSTRUMENTS}


def _measure(instrument_id: str) -> str:
    item = universe.get(instrument_id)
    bench = item.benchmark_id if item else None
    return f"vs {universe.get(bench).symbol}" if bench else "raw"


def _abnormal_by_horizon(closes: pd.DataFrame) -> dict[int, pd.DataFrame]:
    bench = _benchmarks()
    result = {h: abnormal_forward(closes, h, bench) for h in HORIZONS if h > 0}
    one_day = closes / closes.shift(1) - 1
    reaction = one_day.copy()
    for column, ref in bench.items():
        if column in reaction and ref and ref in one_day:
            reaction[column] = one_day[column] - one_day[ref]
    result[0] = reaction
    return result


def _stats(sample: pd.Series, population: pd.Series) -> dict | None:
    sample, population = sample.dropna(), population.dropna()
    n = len(sample)
    if n < MIN_N or len(population) < 60:
        return None
    mean, baseline = float(sample.mean()), float(population.mean())
    var = float(sample.var(ddof=1)) / n + float(population.var(ddof=1)) / len(population)
    t_stat = (mean - baseline) / np.sqrt(var) if var > 0 else 0.0
    p_value = float(2 * sstats.t.sf(abs(t_stat), df=max(n - 1, 1)))
    return {
        "n": n, "mean": mean, "median": float(sample.median()), "baseline": baseline,
        "edge": mean - baseline, "hit_rate": float((sample > 0).mean()), "t_stat": float(t_stat), "p_value": p_value,
    }


def _sample(abn: pd.DataFrame, instrument_id: str, dates: pd.DatetimeIndex) -> pd.Series:
    if instrument_id not in abn:
        return pd.Series(dtype=float)
    return abn[instrument_id].reindex(dates)


def compute_all(progress=None) -> int:
    closes = data.closes()
    events = data.events_frame()
    if closes.empty or events.empty:
        return 0
    abn = _abnormal_by_horizon(closes)
    targets = [item.id for item in universe.INSTRUMENTS if item.tradable or item.id in ("index:vix", "index:tnx")]
    computed_at = db.now_iso()
    records: list[tuple] = []

    def add(event_type: str, instrument_id: str, horizon: int, result: dict | None, measure: str) -> None:
        if result:
            records.append((event_type, instrument_id, horizon, result["n"], result["mean"], result["median"],
                            result["baseline"], result["edge"], result["hit_rate"], result["t_stat"],
                            result["p_value"], measure, computed_at))

    for event_type, group in events.groupby("type"):
        if progress:
            progress(f"event study {event_type}")
        scope = EVENT_TYPES.get(event_type, {}).get("scope", "macro")
        if scope == "asset":
            pooled: dict[int, dict[str, list[float]]] = {h: {} for h in HORIZONS}
            for instrument_id, rows in group.groupby("instrument_id"):
                dates = pd.DatetimeIndex(rows["date"])
                asset_class = universe.get(instrument_id).asset_class if universe.get(instrument_id) else "stock"
                for h in HORIZONS:
                    sample = _sample(abn[h], instrument_id, dates)
                    add(event_type, instrument_id, h, _stats(sample, abn[h].get(instrument_id, pd.Series(dtype=float))),
                        _measure(instrument_id))
                    pooled[h].setdefault(asset_class, []).extend(sample.dropna().tolist())
            for h in HORIZONS:
                for asset_class, values in pooled[h].items():
                    population = abn[h][[c for c in abn[h].columns if c.startswith(f"{asset_class}:")]].stack()
                    add(event_type, f"pool:{asset_class}", h, _stats(pd.Series(values), population), "vs SPY")
        else:
            dates = pd.DatetimeIndex(group["date"].drop_duplicates())
            for instrument_id in targets:
                for h in HORIZONS:
                    if instrument_id not in abn[h]:
                        continue
                    first = dates.min()
                    population = abn[h][instrument_id][abn[h].index >= first - pd.Timedelta(days=365)]
                    add(event_type, instrument_id, h, _stats(_sample(abn[h], instrument_id, dates), population),
                        _measure(instrument_id))

    with db.session() as conn:
        conn.execute("DELETE FROM event_impact")
        conn.executemany(
            """INSERT INTO event_impact(type,instrument_id,horizon,n,mean,median,baseline,edge,hit_rate,t_stat,p_value,measure,computed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            records,
        )
    return len(records)


def impact(event_type: str, instrument_id: str) -> dict | None:
    """Stored stats for one (event, asset) pair, falling back to the asset-class pool."""
    item = universe.get(instrument_id)
    candidates = [instrument_id] + ([f"pool:{item.asset_class}"] if item else [])
    for candidate in candidates:
        rows = db.rows("SELECT * FROM event_impact WHERE type=? AND instrument_id=? ORDER BY horizon", (event_type, candidate))
        if rows and max(row["n"] for row in rows) >= MIN_N:
            return {
                "event_type": event_type, "label": label(event_type), "instrument_id": instrument_id,
                "pooled": candidate != instrument_id, "basis": candidate, "measure": rows[0]["measure"],
                "horizons": {row["horizon"]: _public(row) for row in rows},
            }
    return None


def _public(row: dict) -> dict:
    return {key: row[key] for key in ("n", "mean", "median", "baseline", "edge", "hit_rate", "t_stat", "p_value")}


def strongest_for(instrument_id: str, horizon: int = 20, limit: int = 12, min_abs_t: float = 2.0) -> list[dict]:
    """Event types with the most statistically reliable effect on this asset."""
    rows = db.rows(
        """SELECT * FROM event_impact WHERE instrument_id=? AND horizon=? AND ABS(t_stat)>=?
           ORDER BY ABS(t_stat) DESC LIMIT ?""",
        (instrument_id, horizon, min_abs_t, limit),
    )
    return [{"event_type": row["type"], "label": label(row["type"]), "measure": row["measure"], **_public(row)} for row in rows]


def occurrences(event_type: str, instrument_id: str, limit: int = 40) -> dict:
    """Every past occurrence with what the asset did afterwards (for evidence drill-down)."""
    closes = data.closes()
    events = data.events_frame()
    if closes.empty or events.empty:
        return {"rows": []}
    selected = events[events["type"] == event_type]
    scope = EVENT_TYPES.get(event_type, {}).get("scope")
    if scope == "asset":
        selected = selected[selected["instrument_id"] == instrument_id]
    selected = selected.sort_values("date", ascending=False).head(limit)
    abn = _abnormal_by_horizon(closes)
    out = []
    for row in selected.itertuples():
        entry = {"date": row.date.date().isoformat(), "title": row.title, "surprise": _num(row.surprise)}
        for h in HORIZONS:
            series = abn[h].get(instrument_id)
            entry[f"r{h}"] = _num(series.get(row.date)) if series is not None else None
        out.append(entry)
    return {"event_type": event_type, "label": label(event_type), "instrument_id": instrument_id,
            "measure": _measure(instrument_id), "rows": out}


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(number) else number


def recent_events(days: int = 10, instrument_id: str | None = None) -> list[dict]:
    """Structured events in the last N calendar days that are relevant to an asset (or all)."""
    since = (pd.Timestamp.today() - pd.Timedelta(days=days)).date().isoformat()
    if instrument_id:
        return db.rows(
            "SELECT * FROM events WHERE date>=? AND (instrument_id IS NULL OR instrument_id=?) ORDER BY date DESC",
            (since, instrument_id),
        )
    return db.rows("SELECT * FROM events WHERE date>=? ORDER BY date DESC", (since,))


def most_affected(event_type: str, horizon: int = 20, limit: int = 6) -> list[dict]:
    """Assets with the most reliable historical reaction to an event type."""
    rows = db.rows(
        """SELECT instrument_id, n, edge, hit_rate, t_stat FROM event_impact
           WHERE type=? AND horizon=? AND n>=? AND instrument_id NOT LIKE 'pool:%'
           ORDER BY ABS(t_stat) DESC LIMIT ?""",
        (event_type, horizon, 8, limit),
    )
    for row in rows:
        item = universe.get(row["instrument_id"])
        row["symbol"] = item.symbol if item else row["instrument_id"]
    return rows
