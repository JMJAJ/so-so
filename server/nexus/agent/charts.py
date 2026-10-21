"""Chart payloads the AI can put in chat (via the `show_chart` tool).

Charts are built from stored data, not from numbers the model types, so what the
user sees is real. The only exception is `kind="bar"` with model-supplied values,
which the UI labels as such.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .. import data, db, paper, universe
from ..research import analogs, event_study
from ..taxonomy import label

MAX_POINTS = 360
MAX_COMPARE = 6
KINDS = ("price", "compare", "analogs", "event_study", "equity", "bar")


def _thin(series: pd.Series) -> pd.Series:
    series = series.dropna()
    if len(series) <= MAX_POINTS:
        return series
    step = int(np.ceil(len(series) / MAX_POINTS))
    return pd.concat([series.iloc[::step], series.iloc[[-1]]]).loc[lambda s: ~s.index.duplicated(keep="last")]


def _points(series: pd.Series) -> list[dict]:
    return [{"x": ts.date().isoformat(), "y": round(float(v), 6)} for ts, v in _thin(series).items()]


def _start(years: float) -> str:
    return (date.today() - timedelta(days=int(365 * max(0.1, min(years, 10))))).isoformat()


def _price(instrument: str, years: float) -> tuple[dict, str]:
    item = universe.require(instrument)
    bars = data.ohlcv(item.id, _start(years))
    if bars.empty:
        raise ValueError(f"No price history for {item.symbol}")
    close = bars["close"]
    levels = []
    rec = db.one("SELECT * FROM recommendations WHERE instrument_id=? AND status='open'", (item.id,))
    if rec:
        levels = [{"label": "entry", "value": rec["entry_price"], "tone": "amber"},
                  {"label": "stop", "value": rec["stop"], "tone": "bear"},
                  {"label": "target", "value": rec["target"], "tone": "bull"}]
    first = close.index[0].date().isoformat()
    markers = [{"x": row["date"], "label": row["type"].replace("_", " ")} for row in db.rows(
        """SELECT date, type FROM events WHERE date>=? AND (instrument_id=? OR (instrument_id IS NULL AND type IN
           ('rate_hike','rate_cut','vix_spike','equity_selloff','oil_shock_up','oil_shock_down'))) ORDER BY date""",
        (first, item.id))]
    change = close.iloc[-1] / close.iloc[0] - 1
    chart = {"kind": "line", "title": f"{item.symbol} · {item.name}", "format": "price",
             "series": [{"name": item.symbol, "points": _points(close)}], "levels": levels, "markers": markers[-25:]}
    summary = (f"{item.symbol} {first}→{close.index[-1].date()}: {close.iloc[0]:.4g} → {close.iloc[-1]:.4g} "
               f"({change:+.1%}), high {close.max():.4g}, low {close.min():.4g}"
               + (f"; open call levels entry {rec['entry_price']:.4g} stop {rec['stop']:.4g} target {rec['target']:.4g}" if rec else ""))
    return chart, summary


def _compare(instruments: list[str], years: float) -> tuple[dict, str]:
    items = [universe.require(value) for value in instruments[:MAX_COMPARE]]
    if len(items) < 2:
        raise ValueError("compare needs at least two instruments")
    closes = data.closes(_start(years))
    series, parts = [], []
    for item in items:
        if item.id not in closes:
            continue
        col = closes[item.id].dropna()
        rel = col / col.iloc[0] - 1
        series.append({"name": item.symbol, "points": _points(rel)})
        parts.append(f"{item.symbol} {rel.iloc[-1]:+.1%}")
    held = [f"{row['side']} {universe.get(row['instrument_id']).symbol}" for row in db.rows(
        "SELECT instrument_id, side FROM positions WHERE instrument_id IN ({})".format(",".join("?" * len(items))),
        [item.id for item in items])]
    note = f" Open paper positions among these: {', '.join(held)} (a short profits when the price falls)." if held else ""
    return ({"kind": "line", "title": "Performance comparison", "format": "pct", "series": series, "levels": [],
             "markers": []}, f"Return since {closes.index[0].date()}: " + ", ".join(parts) + "." + note)


def _analogs(instrument: str) -> tuple[dict, str]:
    item = universe.require(instrument)
    result = analogs.find(item.id)
    if not result or not result.get("fan"):
        raise ValueError(f"Not enough history for analogs on {item.symbol}")
    return ({"kind": "fan", "title": f"{item.symbol}: what followed the 20 most similar past setups",
             "fan": result["fan"], "horizon": result["horizon"]},
            f"{item.symbol} analogs (k={result['k']}): {result['horizon']}d mean {result['mean_return']:+.2%}, "
            f"median {result['median_return']:+.2%}, up {result['hit_rate']:.0%}, dispersion {result['dispersion']:.1%}")


def _event_study(event_type: str, instrument: str) -> tuple[dict, str]:
    item = universe.require(instrument)
    impact = event_study.impact(event_type, item.id)
    if not impact:
        raise ValueError(f"Fewer than 5 occurrences of {event_type} with data for {item.symbol}")
    bars = [{"label": "day 0" if int(h) == 0 else f"{h}d", "value": s["mean"], "note": f"n={s['n']} t={s['t_stat']:.1f} up {s['hit_rate']:.0%}"}
            for h, s in sorted(impact["horizons"].items(), key=lambda kv: int(kv[0]))]
    h20 = impact["horizons"].get(20) or impact["horizons"].get("20")
    return ({"kind": "bar", "title": f"{item.symbol} after {label(event_type)} ({impact['measure']})", "format": "pct",
             "bars": bars, "note": "Average return after past occurrences, by sessions after the reaction day."},
            f"{label(event_type)} → {item.symbol}: " + (f"20d mean {h20['mean']:+.2%}, up {h20['hit_rate']:.0%}, t={h20['t_stat']:.1f}, n={h20['n']}" if h20 else "see chart"))


def _equity() -> tuple[dict, str]:
    curve = paper.equity_curve()
    state = paper.portfolio()
    series = [{"name": "Paper account", "points": [{"x": p["date"], "y": p["return_pct"] / 100} for p in curve]},
              {"name": "SPY", "points": [{"x": p["date"], "y": p["spy_return_pct"] / 100} for p in curve if p["spy_return_pct"] is not None]}]
    return ({"kind": "line", "title": "Paper equity vs S&P 500", "format": "pct", "series": series, "levels": [], "markers": []},
            f"Equity {state['equity']:,.2f} ({state['return_pct']:+.2f}%), {len(curve)} daily snapshots")


def _bar(title: str, labels: list[str], values: list[float], value_format: str) -> tuple[dict, str]:
    if not labels or len(labels) != len(values):
        raise ValueError("bar needs labels and values of equal length")
    bars = [{"label": str(lbl)[:24], "value": float(v)} for lbl, v in zip(labels[:20], values[:20])]
    return ({"kind": "bar", "title": title or "Comparison", "format": value_format, "bars": bars,
             "note": "Values supplied by the AI from its tool results."}, f"Bar chart of {len(bars)} values")


def show_chart(kind: str, instrument: str | None = None, instruments: list[str] | None = None,
               event_type: str | None = None, years: float = 1.0, title: str | None = None,
               labels: list[str] | None = None, values: list[float] | None = None, value_format: str = "pct") -> dict:
    if kind == "price":
        chart, summary = _price(instrument or "", years)
    elif kind == "compare":
        chart, summary = _compare(instruments or [], years)
    elif kind == "analogs":
        chart, summary = _analogs(instrument or "")
    elif kind == "event_study":
        if not event_type:
            raise ValueError("event_study needs event_type")
        chart, summary = _event_study(event_type, instrument or "")
    elif kind == "equity":
        chart, summary = _equity()
    elif kind == "bar":
        chart, summary = _bar(title or "", labels or [], values or [], value_format)
    else:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if title and kind != "bar":
        chart["title"] = title
    return {"chart": chart, "summary": f"Chart shown to the user. {summary}"}
