"""Event studies: what happened to each asset after each kind of event.

Entry is the close of the event's reaction session (see ingest/events.py), so the
numbers describe returns you could have captured after the news was known.

Measure: market-model abnormal return, i.e. return minus beta x benchmark (SPY for
stocks/ETFs, BTC for alt-coins), with beta from the trailing year; raw return for FX,
commodities, SPY and BTC. `edge` = event mean - the asset's unconditional mean.

Thousands of (event x asset x horizon) tests are run, so plain t-stats produce many
false discoveries. An effect is only `reliable` when it survives a Benjamini-Hochberg
false-discovery correction (q <= 0.10), has n >= 8, and points the same way in the older
and the newer half of its history.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import data, db, universe
from ..taxonomy import EVENT_TYPES, label
from .features import abnormal_forward, rolling_betas

HORIZONS = (0, 5, 10, 20, 40)
MIN_N = 5
RELIABLE_N = 8
FDR_Q = 0.10


def _t_two_sided(t: float, df: int) -> float:
    """Two-sided p-value of a t statistic. scipy is imported here, not at module load, so the
    live server (which only reads stored results) doesn't carry it in memory."""
    from scipy.special import stdtr

    return float(2 * stdtr(df, -abs(t)))


def _benchmarks() -> dict[str, str | None]:
    return {item.id: item.benchmark_id for item in universe.INSTRUMENTS}


def _measure(instrument_id: str) -> str:
    item = universe.get(instrument_id)
    bench = item.benchmark_id if item else None
    return f"vs {universe.get(bench).symbol} (beta-adj.)" if bench else "raw"


def _abnormal_by_horizon(closes: pd.DataFrame) -> dict[int, pd.DataFrame]:
    bench = _benchmarks()
    betas = rolling_betas(closes, bench)
    return {h: abnormal_forward(closes, h, bench, betas) for h in HORIZONS}


def _stats(sample: pd.Series, population: pd.Series) -> dict | None:
    """`sample` is indexed by event date so it can be split into an older and a newer half."""
    sample, population = sample.dropna(), population.dropna()
    n = len(sample)
    if n < MIN_N or len(population) < 60:
        return None
    mean, baseline = float(sample.mean()), float(population.mean())
    var = float(sample.var(ddof=1)) / n + float(population.var(ddof=1)) / len(population)
    t_stat = (mean - baseline) / np.sqrt(var) if var > 0 else 0.0
    p_value = _t_two_sided(t_stat, max(n - 1, 1))
    ordered = sample.sort_index() if isinstance(sample.index, pd.DatetimeIndex) else sample
    half = n // 2
    early = float(ordered.iloc[:half].mean()) - baseline
    late = float(ordered.iloc[half:].mean()) - baseline
    edge = mean - baseline
    stable = bool(half >= 3 and edge != 0 and np.sign(early) == np.sign(edge) == np.sign(late))
    return {
        "n": n, "mean": mean, "median": float(sample.median()), "baseline": baseline,
        "edge": edge, "hit_rate": float((sample > 0).mean()), "t_stat": float(t_stat), "p_value": p_value,
        "edge_early": early, "edge_late": late, "stable": stable,
    }


def benjamini_hochberg(p_values: list[float]) -> list[float]:
    """q-values controlling the false discovery rate across a family of tests."""
    m = len(p_values)
    if m == 0:
        return []
    order = np.argsort(p_values)
    ranked = np.array(p_values)[order] * m / np.arange(1, m + 1)
    q_sorted = np.minimum.accumulate(ranked[::-1])[::-1].clip(max=1.0)
    q = np.empty(m)
    q[order] = q_sorted
    return q.tolist()


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
            records.append({"type": event_type, "instrument_id": instrument_id, "horizon": horizon,
                            "measure": measure, **result})

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
                    pooled[h].setdefault(asset_class, []).append(sample.dropna())
            for h in HORIZONS:
                for asset_class, parts in pooled[h].items():
                    population = abn[h][[c for c in abn[h].columns if c.startswith(f"{asset_class}:")]].stack()
                    add(event_type, f"pool:{asset_class}", h, _stats(pd.concat(parts), population),
                        "vs SPY (beta-adj.)")
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

    # One false-discovery family per tradable horizon: every event type x asset tested at it.
    # The reaction day (h=0) is descriptive only: it isn't tradable (entry is at its close) and
    # for events detected from price moves it is significant by construction.
    for record in records:
        if record["horizon"] == 0:
            record["q_value"], record["reliable"] = None, False
    for h in HORIZONS[1:]:
        family = [r for r in records if r["horizon"] == h]
        for record, q in zip(family, benjamini_hochberg([r["p_value"] for r in family])):
            record["q_value"] = q
            record["reliable"] = bool(q <= FDR_Q and record["stable"] and record["n"] >= RELIABLE_N)

    columns = ("type", "instrument_id", "horizon", "n", "mean", "median", "baseline", "edge", "hit_rate", "t_stat",
               "p_value", "q_value", "edge_early", "edge_late", "stable", "reliable", "measure")
    placeholders = ",".join("?" * (len(columns) + 1))
    with db.session() as conn:
        conn.execute("DELETE FROM event_impact")
        conn.executemany(
            f"INSERT INTO event_impact({','.join(columns)},computed_at) VALUES({placeholders})",
            [tuple(int(r[c]) if isinstance(r[c], bool) else r[c] for c in columns) + (computed_at,) for r in records],
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


PUBLIC_FIELDS = ("n", "mean", "median", "baseline", "edge", "hit_rate", "t_stat", "p_value", "q_value",
                 "edge_early", "edge_late", "stable", "reliable")


def _public(row: dict) -> dict:
    out = {key: row.get(key) for key in PUBLIC_FIELDS}
    out["stable"], out["reliable"] = bool(out["stable"]), bool(out["reliable"])
    return out


def strongest_for(instrument_id: str, horizon: int = 20, limit: int = 12) -> list[dict]:
    """Event types whose effect on this asset survives the false-discovery and stability checks."""
    rows = db.rows(
        """SELECT * FROM event_impact WHERE instrument_id=? AND horizon=? AND reliable=1
           ORDER BY q_value ASC, ABS(t_stat) DESC LIMIT ?""",
        (instrument_id, horizon, limit),
    )
    return [{"event_type": row["type"], "label": label(row["type"]), "measure": row["measure"], **_public(row)}
            for row in rows]


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
        """SELECT instrument_id, n, edge, hit_rate, t_stat, q_value FROM event_impact
           WHERE type=? AND horizon=? AND reliable=1 AND instrument_id NOT LIKE 'pool:%'
           ORDER BY q_value ASC, ABS(t_stat) DESC LIMIT ?""",
        (event_type, horizon, limit),
    )
    for row in rows:
        item = universe.get(row["instrument_id"])
        row["symbol"] = item.symbol if item else row["instrument_id"]
    return rows
