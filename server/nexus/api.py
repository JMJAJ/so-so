"""HTTP API for the NEXUS terminal."""

from __future__ import annotations

import json
import queue
import threading
from contextlib import asynccontextmanager
from datetime import date, timedelta

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import config, data, db, jobs, llm, markets, nlp, paper, recommendations, universe
from .agent import analyst, chat, tools
from .ingest import prices
from .research import analogs, backtest, correlation, event_study, probability, replay, scan
from .research.features import asset_features, regime_frame, regime_label
from .taxonomy import EVENT_TYPES, NEWS_CATEGORIES, label


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    jobs.start_scheduler()
    if not jobs.has_data():
        try:
            jobs.run_async("init")
        except RuntimeError:
            pass
    else:
        # Warm the forecast cache so the first page load doesn't pay for it.
        threading.Thread(target=lambda: scan.forecasts(), daemon=True, name="warm-forecasts").start()
    yield
    jobs.stop_scheduler()


app = FastAPI(title="NEXUS", version="3.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(KeyError)
async def _not_found(_request: Request, exc: KeyError):
    return JSONResponse(status_code=404, content={"detail": str(exc).strip("'\"")})


@app.exception_handler(ValueError)
async def _bad_request(_request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(RuntimeError)
async def _conflict(_request: Request, exc: RuntimeError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


def clean(value):
    """JSON-safe: NaN/inf → None, numpy → Python."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return None if (np.isnan(number) or np.isinf(number)) else number
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (pd.Timestamp, date)):
        return value.isoformat()
    return value


# ── Status ───────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/status")
def status():
    coverage = db.one(
        """SELECT (SELECT COUNT(DISTINCT instrument_id) FROM bars) instruments,
                  (SELECT MAX(date) FROM bars WHERE instrument_id='etf:spy') last_bar,
                  (SELECT COUNT(*) FROM events) events,
                  (SELECT COUNT(*) FROM news) news,
                  (SELECT COUNT(*) FROM news WHERE classified_at IS NOT NULL) news_classified,
                  (SELECT COUNT(*) FROM theme_series WHERE theme='_total') gdelt_days,
                  (SELECT MIN(date) FROM theme_series WHERE theme='_total') gdelt_from,
                  (SELECT COUNT(*) FROM event_impact) event_impact_rows"""
    )
    provider = config.get("llm_provider")
    return clean({
        "has_data": jobs.has_data(),
        "universe_size": len(universe.INSTRUMENTS),
        "coverage": coverage,
        "llm": {"provider": provider, "model": config.get("llm_model"), "fast_model": config.get("llm_fast_model"),
                "key_set": provider in ("ollama", "lmstudio") or config.secret_status().get(
                    llm.PROVIDERS.get(provider, {}).get("key") or "", {}).get("set", False)},
        "analyst_running": analyst.running(),
        "jobs": [{k: j.get(k) for k in ("name", "running", "progress", "last_status", "last_finished", "next_run")}
                 for j in jobs.status()],
        "autopilot": config.get_bool("autopilot"),
    })


# ── Dashboard ────────────────────────────────────────────────────────────────

def _regime_payload() -> dict | None:
    frame = regime_frame()
    if frame.empty:
        return None
    filled = frame.ffill()
    history = filled.iloc[-260:]
    return {
        "current": regime_label(filled.iloc[-1]),
        "as_of": filled.index[-1].date().isoformat(),
        "history": [
            {"date": ts.date().isoformat(), "vix": row.get("vix"), "spy_dd": row.get("spy_dd"),
             "curve": row.get("curve"), "conflict_z": row.get("conflict_z")}
            for ts, row in history.iterrows()
        ],
    }


def _key_events(days: int = 10) -> list[dict]:
    out = []
    held = {r["instrument_id"] for r in recommendations.list_recs("open")}
    for event in event_study.recent_events(days):
        if event["instrument_id"] and event["instrument_id"] not in held:
            continue
        target = event["instrument_id"] or "etf:spy"
        impact = event_study.impact(event["type"], target)
        out.append({**event, "label": label(event["type"]), "impact_on": target,
                    "impact": impact["horizons"].get(20) if impact else None,
                    "most_affected": event_study.most_affected(event["type"]) if not event["instrument_id"] else []})
    return out[:20]


@app.get("/api/dashboard")
def dashboard():
    record = recommendations.track_record()
    port = paper.portfolio()
    ideas = []
    try:
        ideas = scan.ranked(limit=10)
    except Exception as exc:
        db.log("warn", "dashboard", f"scan failed: {exc}")
    return clean({
        "regime": _regime_payload(),
        "ideas": ideas,
        "open_recommendations": recommendations.list_recs("open", 30),
        "brief": analyst.latest_brief(),
        "key_events": _key_events(),
        "headlines": nlp.recent(days=2, limit=12, min_magnitude=2),
        "portfolio": {k: port[k] for k in ("equity", "return_pct", "exposure_pct", "open_count", "pending_count",
                                          "realized", "unrealized")},
        "track": record["overall"],
    })


# ── Universe / assets ────────────────────────────────────────────────────────

@app.get("/api/markets")
def market_hours():
    return markets.overview()


@app.get("/api/universe")
def get_universe():
    quotes = {}
    try:
        quotes = prices.quotes([item.id for item in universe.INSTRUMENTS])
    except Exception:
        pass
    return clean([{**item, "quote": quotes.get(item["id"])} for item in universe.catalog()])


@app.get("/api/forecasts")
def forecasts(asset_class: str | None = None):
    rows = scan.forecasts()
    if asset_class:
        rows = [row for row in rows if row["asset_class"] == asset_class]
    return clean(sorted(rows, key=lambda row: -scan.interest(row)))


@app.get("/api/assets/{instrument}")
def asset(instrument: str, years: float = Query(2.0, ge=0.25, le=10)):
    item = universe.require(instrument)
    start = (date.today() - timedelta(days=int(365 * years))).isoformat()
    bars = data.ohlcv(item.id, start)
    closes = data.closes()
    technicals = None
    if item.id in closes:
        feats = asset_features(closes[item.id].dropna())
        technicals = feats.iloc[-1].to_dict()
    events = db.rows(
        """SELECT id, type, instrument_id, date, title, magnitude, surprise FROM events
           WHERE date>=? AND (instrument_id=? OR instrument_id IS NULL) ORDER BY date""",
        (start, item.id),
    )
    forecast = next((row for row in scan.forecasts() if row["instrument_id"] == item.id), None)
    return clean({
        "instrument": item.to_dict(),
        "market": markets.status(markets.BY_ID[item.market_id], days_back=0.5, days_ahead=4),
        "quote": prices.quote(item.id),
        "bars": [{"t": ts.date().isoformat(), "o": r.open, "h": r.high, "l": r.low, "c": r.close, "v": r.volume}
                 for ts, r in bars.iterrows()] if not bars.empty else [],
        "technicals": technicals,
        "forecast": forecast,
        "events": [{**e, "label": label(e["type"])} for e in events],
        "event_effects": tools.event_effects(item.id),
        "analogs": analogs.find(item.id) if item.id in closes else None,
        "correlations": {"peers": correlation.peers(item.id), "lead_lag": correlation.lead_lag(item.id)},
        "news": nlp.recent(item.id, days=21, limit=40),
        "recommendations": [r for r in recommendations.list_recs(None, 500) if r["instrument_id"] == item.id],
    })


@app.get("/api/assets/{instrument}/event-study")
def asset_event_study(instrument: str, event_type: str):
    item = universe.require(instrument)
    return clean({"impact": event_study.impact(event_type, item.id),
                  **event_study.occurrences(event_type, item.id, limit=60)})


@app.get("/api/events")
def list_events(days: int = Query(30, ge=1, le=3650), event_type: str | None = None):
    since = (date.today() - timedelta(days=days)).isoformat()
    sql = "SELECT * FROM events WHERE date>=?"
    params: list = [since]
    if event_type:
        sql += " AND type=?"
        params.append(event_type)
    rows = db.rows(sql + " ORDER BY date DESC LIMIT 500", params)
    return clean([{**row, "label": label(row["type"])} for row in rows])


@app.get("/api/event-types")
def event_types():
    counts = {row["type"]: row for row in db.rows("SELECT type, COUNT(*) n, MIN(date) first, MAX(date) last FROM events GROUP BY type")}
    return [{"type": key, **meta, "n": counts.get(key, {}).get("n", 0), "first": counts.get(key, {}).get("first"),
             "last": counts.get(key, {}).get("last"), "most_affected": event_study.most_affected(key)}
            for key, meta in EVENT_TYPES.items()]


@app.get("/api/news")
def list_news(instrument: str | None = None, category: str | None = None, days: int = Query(7, ge=1, le=365),
              min_magnitude: int = Query(1, ge=1, le=3), limit: int = Query(150, ge=1, le=500)):
    item = universe.require(instrument) if instrument else None
    return clean(nlp.recent(item.id if item else None, days=days, limit=limit, min_magnitude=min_magnitude,
                            category=category))


@app.get("/api/news-categories")
def news_categories():
    return [{"category": key, "maps_to": value} for key, value in NEWS_CATEGORIES.items()]


# ── Recommendations / portfolio ──────────────────────────────────────────────

class RecommendationIn(BaseModel):
    instrument_id: str
    direction: str
    horizon_days: int = 20
    stop: float
    target: float
    probability: float = 0.55
    confidence: str = "low"
    thesis: str
    evidence: list[dict] = []
    invalidation: str = ""
    trade: bool | None = None


@app.get("/api/recommendations")
def list_recommendations(status: str | None = None):
    return clean(recommendations.list_recs(status, 500))


@app.get("/api/recommendations/{rec_id}")
def get_recommendation(rec_id: str):
    return clean(recommendations.get(rec_id))


@app.post("/api/recommendations")
def create_recommendation(body: RecommendationIn):
    payload = body.model_dump()
    trade = payload.pop("trade")
    if not payload["evidence"]:
        payload["evidence"] = [{"type": "manual", "summary": "Manual idea entered by the user"}]
    return clean(recommendations.create(payload, source="manual", auto_trade=trade))


@app.post("/api/recommendations/{rec_id}/cancel")
def cancel_recommendation(rec_id: str):
    return clean(recommendations.cancel(rec_id))


@app.get("/api/portfolio")
def portfolio():
    return clean({
        **paper.portfolio(),
        "equity_curve": paper.equity_curve(),
        "trades": [
            {**row, "symbol": (universe.get(row["instrument_id"]) or universe.require("etf:spy")).symbol}
            for row in db.rows("SELECT * FROM trades ORDER BY closed_at DESC LIMIT 200")
        ],
    })


@app.post("/api/positions/{position_id}/close")
def close_position(position_id: str):
    result = paper.close_position(position_id, reason="manual")
    rec = db.one("SELECT recommendation_id FROM trades WHERE id=?", (result.get("trade_id"),)) if result.get("trade_id") else None
    return clean({**result, "recommendation_id": rec["recommendation_id"] if rec else None})


@app.get("/api/track-record")
def track_record():
    k, basis = probability.calibration_factor()
    return clean({**recommendations.track_record(), "lessons": recommendations.lessons(),
                  "replay": replay.summary(), "probability_calibration": {"k": k, "basis": basis}})


@app.get("/api/models")
def models():
    return clean(backtest.summary())


# ── AI ───────────────────────────────────────────────────────────────────────

class AnalystRunIn(BaseModel):
    focus: str | None = None
    max_recs: int | None = None


@app.post("/api/analyst/run")
def run_analyst(body: AnalystRunIn):
    if analyst.running():
        raise RuntimeError("An analyst run is already in progress")

    def target() -> None:
        try:
            analyst.run(focus=body.focus, max_recs=body.max_recs)
        except Exception:
            pass

    threading.Thread(target=target, daemon=True, name="analyst").start()
    return {"started": True}


@app.get("/api/runs")
def runs(limit: int = Query(30, ge=1, le=200)):
    return db.rows("SELECT id, kind, started_at, finished_at, status, summary, error FROM runs ORDER BY started_at DESC LIMIT ?", (limit,))


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    row = db.one("SELECT * FROM runs WHERE id=?", (run_id,))
    if not row:
        raise KeyError("Run not found")
    row["transcript"] = db.loads(row["transcript"], [])
    row["recommendations"] = [r for r in recommendations.list_recs(None, 1000) if r.get("run_id") == run_id]
    return clean(row)


class ChatIn(BaseModel):
    message: str
    conversation_id: str | None = None


@app.get("/api/chat")
def chat_list():
    return chat.conversations()


@app.get("/api/chat/{conv_id}")
def chat_messages(conv_id: str):
    return {"id": conv_id, "messages": chat.public_messages(conv_id)}


@app.delete("/api/chat/{conv_id}")
def chat_delete(conv_id: str):
    db.execute("DELETE FROM messages WHERE conversation_id=?", (conv_id,))
    db.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
    return {"deleted": True}


@app.post("/api/chat")
def chat_send(body: ChatIn):
    if not body.message.strip():
        raise ValueError("Message is empty")
    events: queue.Queue = queue.Queue()
    conv_id = body.conversation_id
    if not conv_id or not db.one("SELECT 1 FROM conversations WHERE id=?", (conv_id,)):
        conv_id = chat.new_conversation(body.message.strip()[:60])

    def worker() -> None:
        try:
            chat.send(conv_id, body.message, on_event=events.put)
        except Exception as exc:
            events.put({"type": "error", "message": str(exc)})
        finally:
            events.put(None)

    threading.Thread(target=worker, daemon=True, name="chat").start()

    def stream():
        yield f"data: {json.dumps({'type': 'conversation', 'id': conv_id})}\n\n"
        while True:
            try:
                event = events.get(timeout=15)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            if event is None:
                break
            yield f"data: {json.dumps(event, default=str)}\n\n"
        yield f"data: {json.dumps({'type': 'end'})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Jobs / settings ──────────────────────────────────────────────────────────

@app.get("/api/jobs")
def list_jobs():
    return clean(jobs.status())


@app.post("/api/jobs/{name}/run")
def run_job(name: str):
    jobs.run_async(name)
    return {"started": name}


class SettingsIn(BaseModel):
    values: dict[str, str] = {}
    secrets: dict[str, str] = {}


@app.get("/api/settings")
def get_settings():
    return {"values": config.all_settings(), "secrets": config.secret_status(),
            "providers": llm.PROVIDERS, "asset_classes": ["stock", "etf", "crypto", "forex", "commodity"]}


@app.put("/api/settings")
def put_settings(body: SettingsIn):
    config.set_many(body.values)
    for name, value in body.secrets.items():
        config.set_secret(name, value)
    if "enabled_classes" in body.values:
        scan._cache["at"] = 0
    return get_settings()


@app.post("/api/llm/test")
def llm_test():
    import time

    started = time.perf_counter()
    try:
        provider = llm.create("main")
        reply = provider.complete("Reply with exactly: ok", [{"role": "user", "text": "health check"}], max_tokens=2000)
        return {"ok": bool(reply.text.strip()), "reply": reply.text[:200], "provider": provider.name,
                "model": provider.model, "latency_ms": int((time.perf_counter() - started) * 1000)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "latency_ms": int((time.perf_counter() - started) * 1000)}


@app.get("/api/logs")
def logs(limit: int = Query(100, ge=1, le=1000)):
    return db.rows("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))
