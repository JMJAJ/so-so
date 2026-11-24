"""Live event trader: reacts to breaking news and price shocks within minutes.

The daily analyst looks at the whole market once a day. This module is the fast path:

- a wire alert at `event_trade_level` or above that tags a tradable asset, or
- a move of `event_trade_sigma` of the asset's own daily σ anywhere in the universe, or
- any major alert / 2σ move against a position the paper book holds

starts a short, focused AI run on that one instrument. The run follows the `event-trade`
skill: confirm the move is real, measure what followed past shocks like it
(`shock_reaction`), and buy, sell short, close the held position, or do nothing. The server
still computes every probability and sizes the trade by its evidence tier.

Each (instrument, day, direction) triggers once, runs go one at a time, and at most
`event_trade_max_per_hour` start per hour. Works with or without phone notifications.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone

from .. import config, db, llm, recommendations, universe

_lock = threading.Lock()
_seen: dict[str, float] = {}
_started: deque[float] = deque()
SEEN_TTL_S = 36 * 3600
HELD_ADVERSE_SIGMA = 2.0
MAX_STEPS = 18

TASK = """LIVE EVENT. {reason}

Instrument: {symbol} ({instrument_id}). {position}

You have minutes, not days. Load event-trade and follow it. You may make at most one
propose_recommendation, and only on {instrument_id}. If the book holds {symbol} and the news or the
measured reaction now points against it, close_recommendation is the trade. "No trade" is a fine
answer when the move is noise, already done, or the data looks wrong.

Finish with three sentences at most: what happened, what the measured history says, what you did."""


def enabled() -> bool:
    return config.get_bool("event_trader")


def _held() -> dict[str, dict]:
    """Instrument -> open AI call that has a live paper position in some account."""
    out = {}
    for rec in recommendations.list_recs("open"):
        if db.one("SELECT 1 FROM positions WHERE recommendation_id=?", (rec["id"],)):
            out[rec["instrument_id"]] = rec
    return out


def _rate_ok() -> bool:
    now = time.time()
    while _started and now - _started[0] > 3600:
        _started.popleft()
    return len(_started) < max(1, config.get_int("event_trade_max_per_hour"))


def trigger(instrument_id: str, reason: str, *, side: str, review: bool = False) -> bool:
    """Start a focused run unless this (instrument, day, side) already had one."""
    if not enabled():
        return False
    item = universe.resolve(instrument_id)
    if not item or not item.tradable:
        return False
    if item.asset_class not in config.get("enabled_classes").split(","):
        return False
    from .. import jobs

    if not jobs.llm_ready() or not jobs.has_data():
        return False
    key = f"{item.id}:{datetime.now(timezone.utc).date()}:{side}"
    now = time.time()
    for stale in [k for k, t in _seen.items() if now - t > SEEN_TTL_S]:
        _seen.pop(stale, None)
    if key in _seen or not _rate_ok() or _lock.locked():
        return False
    _seen[key] = now
    _started.append(now)
    threading.Thread(target=_safe_run, args=(item.id, reason, review), daemon=True, name="event-trader").start()
    return True


def _safe_run(instrument_id: str, reason: str, review: bool) -> None:
    try:
        run(instrument_id, reason, review=review)
    except Exception as exc:  # a failed run must never take down the wire or the watch job
        db.log("error", "trader", f"{instrument_id}: {exc}")


def run(instrument_id: str, reason: str, *, review: bool = False, on_event=None) -> dict:
    from . import loop, tools

    if not _lock.acquire(blocking=False):
        raise RuntimeError("An event run is already in progress")
    item = universe.require(instrument_id)
    run_id = f"evt_{uuid.uuid4().hex[:10]}"
    db.execute("INSERT INTO runs(id,kind,started_at,status) VALUES(?,?,?,?)", (run_id, "event", db.now_iso(), "running"))
    try:
        held = _held().get(item.id)
        position = (f"The book HOLDS this: {held['direction']} since {held['created_at'][:10]} at "
                    f"{held['entry_price']:.4g}, stop {held['stop']:.4g}, target {held['target']:.4g}, call "
                    f"{held['id']}, invalidation: {held.get('invalidation') or 'none stated'}."
                    if held else "The book does not hold it.")
        task = TASK.format(reason=reason, symbol=item.symbol, instrument_id=item.id, position=position)
        history = [{"role": "user", "text": task}]
        system = loop.system_prompt("Track record so far:\n" + recommendations.lessons())

        def guard(name: str, payload: dict) -> str | None:
            if name == "propose_recommendation":
                target = universe.resolve(str(payload.get("instrument_id", "")))
                if not target or target.id != item.id:
                    return f"this live run may only trade {item.id}"
                if db.one("SELECT COUNT(*) c FROM recommendations WHERE run_id=?", (run_id,))["c"] >= 1:
                    return "one recommendation per live run"
            if name == "close_recommendation":
                rec = db.one("SELECT instrument_id FROM recommendations WHERE id=?",
                             (payload.get("recommendation_id"),))
                if not rec or rec["instrument_id"] != item.id:
                    return f"this live run may only close the call on {item.id}"
            return None

        new = loop.run(llm.create("main"), system, history, tool_specs=tools.specs(), on_event=on_event,
                       tool_extra={"_source": "event", "_run_id": run_id}, guard=guard, max_steps=MAX_STEPS,
                       effort="medium")
        summary = next((m["text"] for m in reversed(new) if m["role"] == "assistant" and m.get("text")), "")
        transcript = [{k: v for k, v in m.items() if k != "native"} for m in history]
        db.execute("UPDATE runs SET finished_at=?, status=?, summary=?, transcript=? WHERE id=?",
                   (db.now_iso(), "completed", summary, db.dumps(transcript), run_id))
        db.log("info", "trader", f"{item.symbol} ({'review' if review else 'event'}): {summary[:300]}")
        return {"run_id": run_id, "summary": summary}
    except Exception as exc:
        db.execute("UPDATE runs SET finished_at=?, status=?, error=? WHERE id=?",
                   (db.now_iso(), "failed", str(exc), run_id))
        raise
    finally:
        _lock.release()


# ── Triggers ─────────────────────────────────────────────────────────────────

def _z(instrument_id: str, change_pct: float | None) -> float | None:
    from ..notify import daily_sigma

    sigma = daily_sigma(instrument_id)
    if change_pct is None or not sigma:
        return None
    return change_pct / sigma


def on_alerts(alerts: list[dict]) -> int:
    """Wire alerts that just fired. Returns how many runs started."""
    if not enabled() or not alerts:
        return 0
    level = config.get_int("event_trade_level")
    held = _held()
    started = 0
    for alert in sorted(alerts, key=lambda a: -a["level"]):
        moves = alert.get("moves") or {}
        for ticker in [t for t in alert["tickers"] if not t.startswith("index:")][:3]:
            change = (moves.get(ticker) or {}).get("change_pct")
            z = _z(ticker, change)
            mine = ticker in held
            if alert["level"] < level and not (mine and alert["level"] >= 2):
                continue
            side = "up" if (change or 0) >= 0 else "down"
            moved = f" {ticker.split(':')[-1].upper()} is {change:+.1f}% today ({z:+.1f}σ)." if z is not None else ""
            reason = (f"Breaking news (level {alert['level']}, {', '.join(alert['kinds'])}): \"{alert['title']}\" "
                      f"via {alert.get('source') or 'wire'}.{moved}")
            if trigger(ticker, reason, side=f"news-{side}", review=mine):
                started += 1
    return started


def check_moves() -> dict:
    """σ-shocks across the tradable universe (cached quotes, no waiting) and adverse moves on held
    positions. Runs with the 3-minute watch job."""
    if not enabled():
        return {"checked": 0, "started": 0}
    from ..ingest import prices

    classes = set(config.get("enabled_classes").split(","))
    ids = [i.id for i in universe.INSTRUMENTS if i.tradable and i.asset_class in classes]
    quotes = prices.quotes(ids, wait=False)
    held = _held()
    threshold = config.get_float("event_trade_sigma")
    fresh_after = datetime.now(timezone.utc) - timedelta(hours=18)
    candidates = []
    for instrument_id, quote in quotes.items():
        if quote.get("stale") or not quote.get("as_of") or quote.get("change_pct") is None:
            continue
        try:
            as_of = datetime.fromisoformat(quote["as_of"])
        except ValueError:
            continue
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        if as_of < fresh_after:
            continue
        z = _z(instrument_id, quote["change_pct"])
        if z is None:
            continue
        rec = held.get(instrument_id)
        adverse = rec and ((rec["direction"] == "long" and z <= -HELD_ADVERSE_SIGMA)
                           or (rec["direction"] == "short" and z >= HELD_ADVERSE_SIGMA))
        if abs(z) >= threshold or adverse:
            candidates.append((abs(z) + (10 if adverse else 0), instrument_id, quote, z, bool(adverse)))
    started = 0
    for _score, instrument_id, quote, z, adverse in sorted(candidates, reverse=True):
        symbol = instrument_id.split(":")[-1].upper()
        reason = (f"{symbol} is {quote['change_pct']:+.1f}% today at {quote['price']:.4g}, a {z:+.1f}σ move."
                  + (" It moves against the position the book holds." if adverse else "")
                  + " Find out why (breaking_news, recent_news) before deciding.")
        if trigger(instrument_id, reason, side="up" if z > 0 else "down", review=adverse):
            started += 1
    return {"checked": len(quotes), "candidates": len(candidates), "started": started}


def recent_runs(limit: int = 20) -> list[dict]:
    return db.rows("SELECT id, started_at, finished_at, status, summary, error FROM runs WHERE kind='event' "
                   "ORDER BY started_at DESC LIMIT ?", (limit,))


def status() -> dict:
    return {"enabled": enabled(), "running": _lock.locked(), "started_last_hour": len(_started),
            "settings": {k: config.get(k) for k in ("event_trade_level", "event_trade_sigma",
                                                    "event_trade_max_per_hour")},
            "recent": json.loads(json.dumps(recent_runs(10), default=str))}
