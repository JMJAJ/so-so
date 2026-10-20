"""Tools the AI (analyst, chat) and the CLI share. Every tool returns plain JSON data
computed from stored history, so every claim the model makes can be traced."""

from __future__ import annotations

import json
from typing import Callable

import numpy as np
import pandas as pd

from .. import data, db, nlp, paper, recommendations, universe
from ..ingest import prices
from ..research import analogs, backtest, correlation, event_study, scan
from ..research.features import asset_features, regime_frame, regime_label
from ..taxonomy import EVENT_TYPES, NEWS_CATEGORIES

MAX_CHARS = 14000


def _r(value, digits: int = 4):
    if isinstance(value, dict):
        return {k: _r(v, digits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_r(v, digits) for v in value]
    if isinstance(value, (float, np.floating)):
        return None if np.isnan(value) else round(float(value), digits)
    if isinstance(value, np.integer):
        return int(value)
    return value


def _inst(value: str) -> universe.Instrument:
    item = universe.resolve(value or "")
    if not item:
        raise ValueError(f"Unknown instrument '{value}'. Use an id like stock:aapl, etf:spy, crypto:btc, forex:eurusd, commodity:gold.")
    return item


# ── Implementations ──────────────────────────────────────────────────────────

def scan_universe(asset_class: str | None = None, direction: str = "both", limit: int = 15) -> dict:
    rows = scan.ranked(asset_class, direction, min(int(limit), 40))
    return {
        "note": "expected_return/prob_up are the quant model's 20-session forecast. If model_has_edge is false the "
                "walk-forward test found no reliable edge for that asset class and prob_up is just the base rate; "
                "rank by event/analog evidence and news instead.",
        "rows": [{k: row.get(k) for k in ("instrument_id", "symbol", "name", "asset_class", "price", "expected_return",
                                          "prob_up", "score", "model_has_edge", "signals", "vol_20d", "recent_events",
                                          "news_flow", "news_count", "as_of")} for row in rows],
    }


def asset_snapshot(instrument: str) -> dict:
    item = _inst(instrument)
    closes = data.closes()
    if item.id not in closes:
        return {"instrument": item.to_dict(), "error": "no price history stored"}
    feats = asset_features(closes[item.id].dropna())
    last = feats.iloc[-1]
    forecast = next((row for row in scan.forecasts() if row["instrument_id"] == item.id), None)
    return _r({
        "instrument": item.to_dict(),
        "quote": prices.quote(item.id),
        "as_of": feats.index[-1].date().isoformat(),
        "technicals": {k: last.get(k) for k in ("close", "ret_5d", "ret_20d", "ret_60d", "ret_120d", "mom_12_1",
                                                "vol_20d", "vol_ratio", "rsi_14", "dist_sma50", "dist_sma200",
                                                "trend_up", "dist_high_252")},
        "forecast_20d": {k: forecast.get(k) for k in ("expected_return", "prob_up", "sigma", "score", "model_has_edge",
                                                      "signals", "contributions")} if forecast else None,
        "recent_events": [{k: e[k] for k in ("date", "type", "title")} for e in event_study.recent_events(14, item.id)][:12],
        "open_recommendation": next(
            ({k: r[k] for k in ("id", "direction", "entry_price", "stop", "target", "probability", "mark_return")}
             for r in recommendations.list_recs("open") if r["instrument_id"] == item.id), None),
    })


def recent_news(instrument: str | None = None, days: int = 7, category: str | None = None,
                min_magnitude: int = 1, limit: int = 30) -> dict:
    item = _inst(instrument) if instrument else None
    rows = nlp.recent(item.id if item else None, days=int(days), limit=min(int(limit), 60),
                      min_magnitude=int(min_magnitude), category=category)
    return {"rows": [{k: row.get(k) for k in ("published_at", "title", "source", "category", "direction", "magnitude",
                                              "affected", "rationale", "historical_analogs")} for row in rows]}


def event_study_tool(event_type: str, instrument: str) -> dict:
    item = _inst(instrument)
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown event type. Options: {', '.join(EVENT_TYPES)}")
    impact = event_study.impact(event_type, item.id)
    detail = event_study.occurrences(event_type, item.id, limit=15)
    return _r({
        "how_to_read": "horizons are sessions after the reaction day close; 0 = reaction day itself. edge = mean minus "
                       "the asset's normal return over the same period; |t| < 2 is noise; hit_rate = share of positive outcomes.",
        "impact": impact or "fewer than 5 occurrences with data: no reliable history",
        "occurrences": detail.get("rows", []),
    })


def event_effects(instrument: str, horizon: int = 20) -> dict:
    item = _inst(instrument)
    active = []
    for event in event_study.recent_events(10, item.id):
        impact = event_study.impact(event["type"], item.id)
        h = impact["horizons"].get(int(horizon)) if impact else None
        active.append({"date": event["date"], "type": event["type"], "title": event["title"],
                       "history": h, "pooled": impact["pooled"] if impact else None})
    return _r({
        "active_events_last_10d": active,
        "most_reliable_event_effects": event_study.strongest_for(item.id, int(horizon), limit=10, min_abs_t=2.0),
    })


def analogs_tool(instrument: str, horizon: int = 20) -> dict:
    item = _inst(instrument)
    result = analogs.find(item.id, horizon=int(horizon), with_paths=False)
    if not result:
        return {"error": "not enough history for analog search"}
    result["analogs"] = result["analogs"][:12]
    return _r(result)


def correlations_tool(instrument: str) -> dict:
    item = _inst(instrument)
    return _r({"peers": correlation.peers(item.id), "lead_lag_20d": correlation.lead_lag(item.id, 20)[:8]})


def macro_regime() -> dict:
    regime = regime_frame()
    if regime.empty:
        return {"error": "no data"}
    label = regime_label(regime.ffill().iloc[-1])
    macro_events = [e for e in event_study.recent_events(21) if e["instrument_id"] is None]
    levels = {}
    for series_id in ("DFEDTARU", "DGS10", "DGS2", "T10YIE", "BAMLH0A0HYM2", "UNRATE"):
        series = data.macro(series_id)
        if not series.empty:
            levels[series_id] = {"value": series.iloc[-1], "date": series.index[-1].date().isoformat(),
                                 "chg_3m": series.iloc[-1] - series[series.index <= series.index[-1] - pd.Timedelta(days=90)].iloc[-1]
                                 if (series.index <= series.index[-1] - pd.Timedelta(days=90)).any() else None}
    return _r({"regime": label, "fred": levels,
               "macro_events_last_21d": [{k: e[k] for k in ("date", "type", "title")} for e in macro_events[:15]]})


def portfolio_tool() -> dict:
    state = paper.portfolio()
    state["positions"] = [{k: p.get(k) for k in ("id", "symbol", "side", "status", "quantity", "entry_price",
                                                  "current_price", "pnl", "pnl_pct", "stop", "target", "expires_at",
                                                  "recommendation_id")} for p in state["positions"]]
    return _r(state, 2)


def track_record_tool() -> dict:
    record = recommendations.track_record()
    return _r({"summary": recommendations.lessons(), "overall": record["overall"], "calibration": record["calibration"],
               "by_evidence": record["by_evidence"], "by_asset_class": record["by_asset_class"]})


def model_validation(asset_class: str | None = None) -> dict:
    rows = backtest.summary()
    if asset_class:
        rows = [r for r in rows if r["asset_class"] == asset_class]
    return _r({"how_to_read": "walk_forward = out-of-sample performance of the combined quant model (IC = rank "
                              "correlation of forecast vs realized 20-session return; >0.05 with t>2 is meaningful). "
                              "signals = each signal's own IC over the full sample.", "models": rows})


def list_recommendations(status: str = "open") -> dict:
    return {"rows": [{k: r.get(k) for k in ("id", "symbol", "direction", "horizon_days", "entry_price", "stop", "target",
                                            "probability", "confidence", "status", "mark_return", "realized_return",
                                            "excess_return", "created_at", "thesis")}
                     for r in recommendations.list_recs(status if status != "all" else None, 50)]}


WEAK_EVIDENCE_CAP = 0.58
STRONG_EVIDENCE_CAP = 0.70


def _strongest_active_event(instrument_id: str, horizon_days: int) -> dict | None:
    """The most reliable (largest |t|, n >= 8) historical effect among events of the last 10 days,
    at the measured horizon closest to the call's horizon."""
    horizon = min(event_study.HORIZONS[1:], key=lambda h: abs(h - horizon_days))
    best = None
    for event in event_study.recent_events(10, instrument_id):
        impact = event_study.impact(event["type"], instrument_id)
        stats = impact["horizons"].get(horizon) if impact else None
        if stats and stats["n"] >= 8 and (best is None or abs(stats["t_stat"]) > abs(best["t_stat"])):
            best = {"type": event["type"], "horizon": horizon, **stats}
    return best


def _evidence_cap(item: universe.Instrument, horizon_days: int, snapshot: dict | None) -> tuple[float, str]:
    """Server-side check of evidence strength; the model's own quoted t-stats aren't trusted."""
    if snapshot and snapshot.get("model_has_edge"):
        return STRONG_EVIDENCE_CAP, f"the {item.asset_class} quant model has a validated walk-forward edge"
    event = _strongest_active_event(item.id, horizon_days)
    if event and abs(event["t_stat"]) >= 2:
        return STRONG_EVIDENCE_CAP, (f"active {event['type']} has a reliable {event['horizon']}d history "
                                     f"(t={event['t_stat']:.1f}, n={event['n']})")
    reason = f"no validated model edge for {item.asset_class}s and no event from the last 10 days with |t| >= 2"
    if event:
        reason += f" (best: {event['type']}, t={event['t_stat']:.1f}, n={event['n']})"
    return WEAK_EVIDENCE_CAP, reason


def _position_status(rec: dict) -> str:
    if not rec.get("position_id"):
        if rec.get("trade_note"):
            return (f"NOT OPENED: no paper position was opened ({rec['trade_note']}). The recommendation is "
                    "still recorded and will be scored on its own.")
        return "NOT OPENED: autopilot is off, so this is tracked as a call only."
    position = db.one("SELECT * FROM positions WHERE id=?", (rec["position_id"],))
    if not position:
        return "NOT OPENED: the order was cancelled at fill time (price already through the stop)."
    if position["status"] == "pending":
        return (f"PENDING: {position['side']} {position['quantity']:g} {rec['symbol']} will fill at the next "
                "market open.")
    return (f"OPENED: {position['side']} {position['quantity']:g} {rec['symbol']} filled at "
            f"{position['entry_price']:.4g}.")


def propose_recommendation(**payload) -> dict:
    source = payload.pop("_source", "chat")
    run_id = payload.pop("_run_id", None)
    item = _inst(payload.get("instrument_id", ""))
    snapshot = next((row for row in scan.forecasts() if row["instrument_id"] == item.id), None)
    stated = float(payload.get("probability", 0.5))
    cap, reason = _evidence_cap(item, int(payload.get("horizon_days") or 20), snapshot)
    calibration_note = None
    if stated > cap:
        calibration_note = f"Probability capped from {stated:.2f} to {cap:.2f}: {reason}."
        payload["probability"] = cap
        payload["evidence"] = [*(payload.get("evidence") or []),
                               {"type": "calibration", "summary": calibration_note}]
        if cap == WEAK_EVIDENCE_CAP:
            payload["confidence"] = "low"
    rec = recommendations.create({**payload, "instrument_id": item.id}, source=source, run_id=run_id,
                                 signal_snapshot=snapshot)
    status = _position_status(rec)
    result = {
        "paper_position": status,
        "recorded": {k: rec.get(k) for k in ("id", "symbol", "direction", "entry_price", "stop", "target",
                                             "probability", "confidence")},
        "instruction": "Report the paper_position line to the user exactly as stated.",
    }
    if calibration_note:
        result["calibration"] = calibration_note
    return result


def show_chart(**kwargs) -> dict:
    from .charts import show_chart as build

    return build(**kwargs)


# ── Registry ─────────────────────────────────────────────────────────────────

_INSTR = {"type": "string", "description": "Instrument id (stock:aapl, etf:tlt, crypto:btc, forex:eurusd, commodity:gold) or symbol"}

TOOLS: dict[str, dict] = {
    "scan_universe": {
        "fn": scan_universe,
        "description": "Rank the tradable universe by today's quant forecast and evidence strength. Start here to find candidates.",
        "parameters": {"type": "object", "properties": {
            "asset_class": {"type": "string", "enum": ["stock", "etf", "crypto", "forex", "commodity"]},
            "direction": {"type": "string", "enum": ["long", "short", "both"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 40}}},
    },
    "asset_snapshot": {
        "fn": asset_snapshot,
        "description": "Price, technical state, 20-session quant forecast with signal breakdown, and recent events for one instrument.",
        "parameters": {"type": "object", "properties": {"instrument": _INSTR}, "required": ["instrument"]},
    },
    "recent_news": {
        "fn": recent_news,
        "description": "Classified headlines (category, direction, magnitude, affected assets, and which historical event types they map to).",
        "parameters": {"type": "object", "properties": {
            "instrument": _INSTR, "days": {"type": "integer", "minimum": 1, "maximum": 60},
            "category": {"type": "string", "enum": list(NEWS_CATEGORIES)},
            "min_magnitude": {"type": "integer", "minimum": 1, "maximum": 3},
            "limit": {"type": "integer", "minimum": 1, "maximum": 60}}},
    },
    "event_study": {
        "fn": event_study_tool,
        "description": "What this instrument historically did after a given event type: per-horizon mean, edge vs normal, hit rate, t-stat, n, plus each past occurrence.",
        "parameters": {"type": "object", "properties": {
            "event_type": {"type": "string", "enum": list(EVENT_TYPES)}, "instrument": _INSTR},
            "required": ["event_type", "instrument"]},
    },
    "event_effects": {
        "fn": event_effects,
        "description": "Events from the last 10 days that touch this instrument with their measured historical effect, plus the event types with the most reliable effect on it.",
        "parameters": {"type": "object", "properties": {"instrument": _INSTR, "horizon": {"type": "integer", "enum": [5, 10, 20, 40]}},
                       "required": ["instrument"]},
    },
    "analogs": {
        "fn": analogs_tool,
        "description": "Past dates whose asset + macro state most resembles today, and what the asset did next (mean/median forward return, hit rate, dispersion).",
        "parameters": {"type": "object", "properties": {"instrument": _INSTR, "horizon": {"type": "integer", "enum": [5, 10, 20, 40]}},
                       "required": ["instrument"]},
    },
    "correlations": {
        "fn": correlations_tool,
        "description": "Most/least correlated assets and statistically significant lead-lag drivers (e.g. dollar, yields, oil, conflict-news intensity) of the instrument's next-20-session return.",
        "parameters": {"type": "object", "properties": {"instrument": _INSTR}, "required": ["instrument"]},
    },
    "macro_regime": {
        "fn": macro_regime,
        "description": "Current market regime (risk-on/off, VIX, curve, rates, dollar, credit, conflict intensity) and macro events of the last 3 weeks.",
        "parameters": {"type": "object", "properties": {}},
    },
    "portfolio": {
        "fn": portfolio_tool,
        "description": "Paper account: equity, exposure, open/pending positions with P&L.",
        "parameters": {"type": "object", "properties": {}},
    },
    "track_record": {
        "fn": track_record_tool,
        "description": "How past recommendations actually performed: hit rate, returns, calibration, broken down by evidence type and asset class.",
        "parameters": {"type": "object", "properties": {}},
    },
    "model_validation": {
        "fn": model_validation,
        "description": "Walk-forward backtest results of the quant model and each signal, per asset class.",
        "parameters": {"type": "object", "properties": {"asset_class": {"type": "string", "enum": ["stock", "etf", "crypto", "forex", "commodity"]}}},
    },
    "list_recommendations": {
        "fn": list_recommendations,
        "description": "List recommendations by status.",
        "parameters": {"type": "object", "properties": {"status": {"type": "string", "enum": ["open", "closed", "cancelled", "all"]}}},
    },
    "show_chart": {
        "fn": show_chart,
        "description": "Display a chart to the user in the chat, built from stored data. Use it whenever a picture helps: "
                       "price (one instrument, with event markers and any open call's entry/stop/target), compare (2-6 "
                       "instruments, % return), analogs (fan of forward paths after similar setups), event_study (avg "
                       "return by horizon after an event type), equity (paper account vs S&P 500), or bar (your own "
                       "labels/values taken from tool results). You get back a one-line summary.",
        "parameters": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["price", "compare", "analogs", "event_study", "equity", "bar"]},
            "instrument": _INSTR,
            "instruments": {"type": "array", "items": {"type": "string"}, "description": "For compare: 2-6 instruments"},
            "event_type": {"type": "string", "enum": list(EVENT_TYPES)},
            "years": {"type": "number", "minimum": 0.1, "maximum": 10, "description": "Lookback for price/compare (default 1)"},
            "title": {"type": "string"},
            "labels": {"type": "array", "items": {"type": "string"}, "description": "For bar"},
            "values": {"type": "array", "items": {"type": "number"}, "description": "For bar; fractions for pct"},
            "value_format": {"type": "string", "enum": ["pct", "number", "money"]}},
            "required": ["kind"]},
    },
    "propose_recommendation": {
        "fn": propose_recommendation,
        "description": ("Record a recommendation (and, if autopilot is on, open a paper position sized by the risk budget). "
                        "Only call when the evidence supports it. The server caps probability at 0.58 when there is no "
                        "validated model edge and no event from the last 10 days with |t| >= 2 (0.70 otherwise). The "
                        "result's paper_position line says whether a position OPENED, is PENDING or was NOT OPENED."),
        "parameters": {"type": "object", "properties": {
            "instrument_id": _INSTR,
            "direction": {"type": "string", "enum": ["long", "short"]},
            "horizon_days": {"type": "integer", "minimum": 5, "maximum": 40, "description": "Trading sessions to hold"},
            "stop": {"type": "number", "description": "Invalidation price (below current for long, above for short)"},
            "target": {"type": "number", "description": "Take-profit price"},
            "probability": {"type": "number", "minimum": 0.5, "maximum": 0.95, "description": "Calibrated probability the trade is profitable at exit"},
            "expected_return": {"type": "number", "description": "Expected return as a fraction, e.g. 0.03"},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "thesis": {"type": "string", "description": "2-5 sentences: why, citing the numbers"},
            "catalysts": {"type": "array", "items": {"type": "string"}},
            "evidence": {"type": "array", "description": "Each item cites one tool result", "items": {"type": "object", "properties": {
                "type": {"type": "string", "enum": ["event_study", "analogs", "quant_model", "correlation", "news", "macro", "technical"]},
                "summary": {"type": "string", "description": "e.g. 'After rate_cut, GLD 20d +4.1% vs normal, 82% hit, t=2.1, n=11'"},
                "n": {"type": "integer"}, "stat": {"type": "number"}}, "required": ["type", "summary"]}},
            "invalidation": {"type": "string", "description": "What would prove the thesis wrong"}},
            "required": ["instrument_id", "direction", "horizon_days", "stop", "target", "probability", "confidence", "thesis", "evidence"]},
    },
}


def specs(exclude: tuple[str, ...] = ()) -> list[dict]:
    return [{"name": name, "description": tool["description"], "parameters": tool["parameters"]}
            for name, tool in TOOLS.items() if name not in exclude]


def call(name: str, arguments: dict, *, extra: dict | None = None) -> tuple[str, bool]:
    """Run a tool; returns (json_text, is_error). Errors go back to the model as data."""
    tool = TOOLS.get(name)
    if not tool:
        return json.dumps({"error": f"unknown tool {name}"}), True
    if "__invalid_json__" in (arguments or {}):
        return json.dumps({"error": "tool input was not valid JSON; resend the call"}), True
    try:
        kwargs = dict(arguments or {})
        if name == "propose_recommendation" and extra:
            kwargs.update(extra)
        result = tool["fn"](**kwargs)
        text = json.dumps(result, default=str)
        if len(text) > MAX_CHARS and name != "show_chart":  # chart payloads go to the UI, not the model
            text = text[:MAX_CHARS] + '..."[truncated]"'
        return text, False
    except (ValueError, KeyError, TypeError) as exc:
        return json.dumps({"error": str(exc)}), True
    except Exception as exc:  # unexpected failure: still report to the model rather than crash the loop
        db.log("error", "tool", f"{name}: {exc}")
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"}), True


Runner = Callable[[str, dict], tuple[str, bool]]
