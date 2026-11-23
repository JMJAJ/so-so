"""Daily analyst run: scan → shortlist → investigate with tools → 0..N recommendations."""

from __future__ import annotations

import json
import threading
import uuid

from .. import memory, config, db, llm, recommendations
from ..research import scan
from ..research.features import regime_frame, regime_label
from . import loop, tools

_lock = threading.Lock()

TASK = """Daily research run. Investigate the shortlist below (you may also scan for others), then
record your best ideas with propose_recommendation — at most {max_recs} new ones. The server computes
each call's probability from the data and rejects anything below {min_prob:.0%}; a rejection is an
answer, not an error to work around. Zero is a fine answer when nothing has real evidence. Skip instruments
that already have an open recommendation. Prefer ideas where several independent kinds of
evidence agree (event history, analogs, quant model, lead-lag drivers, news).

Before recording any call, load pre-trade-checklist and follow it; load event-playbook and news-triage
before leaning on events or headlines. Then review the open recommendations with position-review
(load it first): hold by default, close_recommendation only when an invalidation condition has
actually happened.

Finish with a short market brief (what matters this week, what you recommended and why, what you
looked at and rejected)."""


def _shortlist(limit: int) -> list[dict]:
    held = {r["instrument_id"] for r in recommendations.list_recs("open")}
    rows = [row for row in scan.ranked(limit=limit * 3) if row["instrument_id"] not in held]
    return rows[:limit]


def run(*, max_recs: int | None = None, focus: str | None = None, on_event=None) -> dict:
    if not _lock.acquire(blocking=False):
        raise RuntimeError("An analyst run is already in progress")
    run_id = f"run_{uuid.uuid4().hex[:10]}"
    db.execute("INSERT INTO runs(id,kind,started_at,status) VALUES(?,?,?,?)", (run_id, "analyst", db.now_iso(), "running"))
    def created() -> int:
        return db.one("SELECT COUNT(*) c FROM recommendations WHERE run_id=?", (run_id,))["c"]

    try:
        scan.forecasts(refresh=True)
        max_recs = max_recs if max_recs is not None else config.get_int("analyst_max_recs")
        min_prob = config.get_float("min_probability")
        shortlist = _shortlist(config.get_int("analyst_shortlist"))
        regime = regime_frame()
        portfolio = tools.portfolio_tool()
        brief = {
            "regime": regime_label(regime.ffill().iloc[-1]) if not regime.empty else None,
            "candidates": [{k: row.get(k) for k in ("instrument_id", "symbol", "asset_class", "price", "expected_return",
                                                     "prob_up", "model_has_edge", "signals", "recent_events", "news_flow")}
                           for row in shortlist],
            "portfolio": {k: portfolio.get(k) for k in ("equity", "exposure_pct", "open_count", "pending_count")},
            "open_recommendations": [f"{r['symbol']} {r['direction']}" for r in recommendations.list_recs("open")],
        }
        task = TASK.format(max_recs=max_recs, min_prob=min_prob)
        if focus:
            task += f"\n\nThe user asked you to focus on: {focus}"
        history = [{"role": "user", "text": f"{task}\n\n```json\n{json.dumps(brief, default=str)}\n```"}]
        system = loop.system_prompt("Track record so far:\n" + recommendations.lessons())

        def guard(name: str, payload: dict) -> str | None:
            if name != "propose_recommendation":
                return None
            if created() >= max_recs:
                return f"limit of {max_recs} new recommendations reached for this run"
            return None

        new = loop.run(llm.create("main"), system, history, tool_specs=tools.specs(), on_event=on_event,
                       tool_extra={"_source": "analyst", "_run_id": run_id}, guard=guard, max_steps=40, effort="high")
        summary = next((m["text"] for m in reversed(new) if m["role"] == "assistant" and m.get("text")), "")
        transcript = [{k: v for k, v in m.items() if k != "native"} for m in history]
        db.execute("UPDATE runs SET finished_at=?, status=?, summary=?, transcript=? WHERE id=?",
                   (db.now_iso(), "completed", summary, db.dumps(transcript), run_id))
        db.log("info", "analyst", f"Run {run_id} finished with {created()} recommendation(s)")
        return {"run_id": run_id, "recommendations": created(), "summary": summary}
    except Exception as exc:
        db.execute("UPDATE runs SET finished_at=?, status=?, error=? WHERE id=?",
                   (db.now_iso(), "failed", str(exc), run_id))
        db.log("error", "analyst", f"Run {run_id} failed: {exc}")
        raise
    finally:
        _lock.release()
        memory.trim()


def running() -> bool:
    return _lock.locked()


def latest_brief() -> dict | None:
    row = db.one("SELECT id, started_at, finished_at, status, summary, error FROM runs WHERE kind='analyst' "
                 "ORDER BY started_at DESC LIMIT 1")
    return row

