"""Recommendation lifecycle and the track record that verifies them.

Every recommendation is scored on its own virtual path (entry at the price when it
was made, stop/target checked on daily highs/lows, else closed at the horizon),
whether or not autopilot traded it. That is the AI's report card.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone

from . import accounts, config, db, live, paper, universe
from .ingest import prices

CONFIDENCE = ("low", "medium", "high")


def _validate(payload: dict, price: float) -> dict:
    direction = str(payload.get("direction", "")).lower()
    if direction not in ("long", "short"):
        raise ValueError("direction must be long or short")
    horizon = int(payload.get("horizon_days") or 20)
    if not 3 <= horizon <= 60:
        raise ValueError("horizon_days must be between 3 and 60")
    stop, target = float(payload["stop"]), float(payload["target"])
    if direction == "long" and not stop < price < target:
        raise ValueError(f"long needs stop < price ({price:g}) < target")
    if direction == "short" and not target < price < stop:
        raise ValueError(f"short needs target < price ({price:g}) < stop")
    probability = float(payload.get("probability", 0.5))
    if not 0.0 < probability < 1.0:
        raise ValueError("probability must be between 0 and 1")
    confidence = str(payload.get("confidence", "low")).lower()
    if confidence not in CONFIDENCE:
        confidence = "low"
    thesis = str(payload.get("thesis", "")).strip()
    if len(thesis) < 20:
        raise ValueError("thesis is required")
    evidence = payload.get("evidence") or []
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("at least one evidence item is required")
    return {
        "direction": direction, "horizon_days": horizon, "stop": stop, "target": target,
        "probability": probability, "confidence": confidence, "thesis": thesis, "evidence": evidence,
        "catalysts": payload.get("catalysts") or [], "invalidation": str(payload.get("invalidation", "")),
        "expected_return": payload.get("expected_return"),
        "stated_probability": payload.get("stated_probability"),
        "base_probability": payload.get("base_probability"),
    }


def create(payload: dict, *, source: str, run_id: str | None = None, signal_snapshot: dict | None = None,
           auto_trade: bool | None = None, skills: list[str] | None = None) -> dict:
    item = universe.require(str(payload.get("instrument_id") or payload.get("symbol") or ""))
    if not item.tradable:
        raise ValueError(f"{item.symbol} is research-only")
    existing = db.one("SELECT * FROM recommendations WHERE instrument_id=? AND status='open'", (item.id,))
    if existing:
        if traded(existing):
            raise ValueError(f"Already holding {item.symbol} in this account (call {existing['id']})")
        if _positions_of(existing["id"]):
            # Another account holds this call: trade the same call here instead of replacing it.
            rec = get(existing["id"])
            try:
                return trade(existing["id"])
            except (ValueError, KeyError) as exc:
                rec["trade_note"] = str(exc)
                return rec
        # A call that no account traded is replaced.
        _close(_public(existing), quote_price(item.id) or existing["entry_price"], "superseded")
    quote = prices.quote(item.id)
    if not quote or quote["price"] is None:
        raise ValueError(f"No price for {item.symbol}")
    clean = _validate(payload, quote["price"])
    rec_id = f"rec_{uuid.uuid4().hex[:10]}"
    expires_at = paper.expiry_from_now(clean["horizon_days"])
    db.execute(
        """INSERT INTO recommendations(id,created_at,instrument_id,direction,horizon_days,entry_price,stop,target,
           expected_return,probability,stated_probability,base_probability,confidence,thesis,catalysts,evidence,
           invalidation,signal_snapshot,source,run_id,status,expires_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (rec_id, db.now_iso(), item.id, clean["direction"], clean["horizon_days"], quote["price"], clean["stop"],
         clean["target"], clean["expected_return"], clean["probability"], clean["stated_probability"],
         clean["base_probability"], clean["confidence"], clean["thesis"], db.dumps(clean["catalysts"]), db.dumps(clean["evidence"]),
         clean["invalidation"], db.dumps(signal_snapshot) if signal_snapshot else None, source, run_id, "open",
         expires_at),
    )
    if skills:
        db.execute("UPDATE recommendations SET skills=? WHERE id=?", (db.dumps(skills), rec_id))
    # The analyst trades its calls in every account with autopilot on; chat and manual calls go
    # to the account in use. `auto_trade` overrides the account setting (tests, API callers).
    if source == "analyst" and auto_trade is None:
        targets = [a for a in accounts.all_accounts() if a["autopilot"]]
    else:
        account = accounts.get()
        should_trade = account["autopilot"] if auto_trade is None else auto_trade
        targets = [account] if should_trade else []
    notes = []
    for account in targets:
        try:
            position = paper.open_position(item.id, clean["direction"], stop=clean["stop"], target=clean["target"],
                                           expires_at=expires_at, recommendation_id=rec_id, source=source,
                                           account_id=account["id"])
            db.execute("UPDATE recommendations SET position_id=COALESCE(position_id, ?) WHERE id=?",
                       (position["id"], rec_id))
        except (ValueError, KeyError) as exc:
            notes.append(f"{account['name']}: {exc}" if len(targets) > 1 else str(exc))
            db.log("warn", "autopilot", f"{item.symbol}: not traded in {account['name']} ({exc})")
    trade_note = "; ".join(notes) or None
    db.log("info", "recommend", f"{clean['direction'].upper()} {item.symbol} {clean['horizon_days']}d "
           f"p={clean['probability']:.2f} ({source})")
    rec = get(rec_id)
    if trade_note:
        rec["trade_note"] = trade_note
    live.publish("recommendations")
    return rec


def _positions_of(rec_id: str, account_id: str | None = None) -> list[dict]:
    """Live paper positions trading this call (in one account, or all of them)."""
    sql = "SELECT * FROM positions WHERE recommendation_id=?"
    params: list = [rec_id]
    if account_id:
        sql += " AND account_id=?"
        params.append(account_id)
    return db.rows(sql, params)


def traded(rec: dict, account_id: str | None = None) -> bool:
    """Whether the call has a live paper position (pending or open) in the account in use."""
    return bool(_positions_of(rec["id"], account_id or accounts.current()))


def quote_price(instrument_id: str) -> float | None:
    quote = prices.quote(instrument_id)
    return quote["price"] if quote and quote["price"] is not None else None


def close_all_open(reason: str) -> int:
    count = 0
    for rec in list_recs("open", 5000):
        _close(rec, quote_price(rec["instrument_id"]) or rec.get("mark_price") or rec["entry_price"], reason)
        count += 1
    return count


def trade(rec_id: str) -> dict:
    """Open a paper position for an open call that doesn't have one."""
    rec = get(rec_id)
    if rec["status"] != "open":
        raise ValueError(f"{rec['symbol']} call is {rec['status']}")
    if traded(rec):
        raise ValueError(f"{rec['symbol']} already has a paper position in this account")
    position = paper.open_position(rec["instrument_id"], rec["direction"], stop=rec["stop"], target=rec["target"],
                                   expires_at=rec["expires_at"], recommendation_id=rec_id, source="manual")
    db.execute("UPDATE recommendations SET position_id=COALESCE(position_id, ?) WHERE id=?", (position["id"], rec_id))
    live.publish("recommendations")
    return get(rec_id)


def _public(row: dict) -> dict:
    item = universe.get(row["instrument_id"])
    out = dict(row)
    for key in ("catalysts", "evidence", "signal_snapshot", "skills", "close_skills"):
        out[key] = db.loads(row.get(key), None if key == "signal_snapshot" else [])
    out["symbol"] = item.symbol if item else row["instrument_id"]
    out["name"] = item.name if item else ""
    out["asset_class"] = item.asset_class if item else ""
    out["traded"] = traded(row)
    return out


def get(rec_id: str) -> dict:
    row = db.one("SELECT * FROM recommendations WHERE id=?", (rec_id,))
    if not row:
        raise KeyError("Recommendation not found")
    return _public(row)


def list_recs(status: str | None = None, limit: int = 200) -> list[dict]:
    if status:
        rows = db.rows("SELECT * FROM recommendations WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit))
    else:
        rows = db.rows("SELECT * FROM recommendations ORDER BY created_at DESC LIMIT ?", (limit,))
    return _live_marks([_public(row) for row in rows])


def _live_marks(recs: list[dict]) -> list[dict]:
    """Mark open calls at the latest quote (the stored mark is only refreshed by the daily job)."""
    open_ids = sorted({rec["instrument_id"] for rec in recs if rec["status"] == "open"})
    if not open_ids:
        return recs
    quotes = prices.quotes(open_ids)
    for rec in recs:
        price = (quotes.get(rec["instrument_id"]) or {}).get("price") if rec["status"] == "open" else None
        if price and rec.get("entry_price"):
            rec["mark_price"] = price
            rec["mark_return"] = _ret(rec["direction"], rec["entry_price"], price)
    return recs


def cancel(rec_id: str, reason: str = "cancelled by user") -> dict:
    rec = get(rec_id)
    if rec["status"] != "open":
        raise ValueError("Only open recommendations can be cancelled")
    for position in _positions_of(rec_id):
        paper.close_position(position["id"], reason="cancelled")
    _close(rec, rec.get("mark_price") or rec["entry_price"], "cancelled")
    db.execute("UPDATE recommendations SET status='cancelled', exit_reason=? WHERE id=?", (reason, rec_id))
    live.publish("recommendations")
    return get(rec_id)


def close_early(rec_id: str, reason: str, *, skills: list[str] | None = None) -> dict:
    """The AI closes an open call before its stop, target or horizon (exit_reason 'ai_review').
    `score_open` later records what holding would have returned, so early closes are measured."""
    rec = get(rec_id)
    if rec["status"] != "open":
        raise ValueError(f"{rec['symbol']} is not open (status {rec['status']})")
    if len(reason.strip()) < 15:
        raise ValueError("Give a concrete reason: which invalidation condition happened, with the data")
    quote = prices.quote(rec["instrument_id"])
    if not quote or quote["price"] is None:
        raise ValueError(f"No price for {rec['symbol']}")
    for position in _positions_of(rec_id):
        paper.close_position(position["id"], reason="ai_review")
    _close(rec, quote["price"], "ai_review")
    db.execute("UPDATE recommendations SET close_skills=?, invalidation=COALESCE(invalidation,'') || ? WHERE id=?",
               (db.dumps(skills or []), f"\n[closed early] {reason.strip()[:400]}", rec_id))
    db.log("info", "recommend", f"AI closed {rec['symbol']} early: {reason.strip()[:200]}")
    return get(rec_id)


def _path_outcome(rec: dict, bars: list[dict]) -> tuple[str, float, str] | None:
    """First stop/target touch on daily bars after the call was made."""
    for bar in bars:
        if bar["low"] is None or bar["high"] is None:
            continue
        o = bar["open"] or bar["close"]
        if rec["direction"] == "long":
            if bar["low"] <= rec["stop"]:
                return "stop", min(o, rec["stop"]), bar["date"]
            if bar["high"] >= rec["target"]:
                return "target", max(o, rec["target"]), bar["date"]
        else:
            if bar["high"] >= rec["stop"]:
                return "stop", max(o, rec["stop"]), bar["date"]
            if bar["low"] <= rec["target"]:
                return "target", min(o, rec["target"]), bar["date"]
    return None


def score_early_closes() -> int:
    """For AI early closes, record what holding to stop/target/horizon would have returned."""
    done = 0
    now = datetime.now(timezone.utc)
    for rec in db.rows("SELECT * FROM recommendations WHERE exit_reason='ai_review' AND hold_return IS NULL"):
        bars = db.rows("SELECT date, open, high, low, close FROM bars WHERE instrument_id=? AND date>? ORDER BY date",
                       (rec["instrument_id"], rec["created_at"][:10]))
        outcome = _path_outcome(rec, bars)
        if not outcome and now >= datetime.fromisoformat(rec["expires_at"]) and bars:
            outcome = ("horizon", bars[-1]["close"], bars[-1]["date"])
        if outcome:
            db.execute("UPDATE recommendations SET hold_return=? WHERE id=?",
                       (_ret(rec["direction"], rec["entry_price"], outcome[1]), rec["id"]))
            done += 1
    return done


def write_postmortems(limit: int = 10) -> int:
    """Ask the fast model for a one-or-two sentence lesson on each newly closed call."""
    from . import llm
    from .agent import skills

    rows = db.rows("SELECT * FROM recommendations WHERE status='closed' AND lesson IS NULL "
                   "ORDER BY closed_at DESC LIMIT ?", (limit,))
    if not rows:
        return 0
    skill = skills.get("post-mortem")
    provider = llm.create("fast")
    written = 0
    for row in rows:
        rec = _public(row)
        facts = {k: rec.get(k) for k in ("symbol", "direction", "horizon_days", "entry_price", "stop", "target",
                                         "probability", "base_probability", "thesis", "evidence", "invalidation",
                                         "skills", "exit_reason", "exit_price", "realized_return", "benchmark_return",
                                         "hold_return", "created_at", "closed_at")}
        try:
            reply = provider.complete(skill.body, [{"role": "user", "text": db.dumps(facts)}], max_tokens=400,
                                      effort="low")
        except Exception as exc:
            db.log("warn", "post-mortem", f"{rec['symbol']}: {exc}")
            break
        text = " ".join((reply.text or "").split())[:400]
        if text:
            db.execute("UPDATE recommendations SET lesson=? WHERE id=?", (text, rec["id"]))
            written += 1
    if written:
        live.publish("recommendations")
    return written


# ── Scoring ──────────────────────────────────────────────────────────────────

def _ret(direction: str, entry: float, exit_price: float) -> float:
    raw = exit_price / entry - 1
    return raw if direction == "long" else -raw


def _benchmark_return(rec: dict, end_date: str) -> float | None:
    item = universe.get(rec["instrument_id"])
    bench = item.benchmark_id if item else None
    if not bench or rec["direction"] != "long":
        return 0.0 if rec["direction"] == "short" else None
    start = db.one("SELECT close FROM bars WHERE instrument_id=? AND date<=? ORDER BY date DESC LIMIT 1",
                   (bench, rec["created_at"][:10]))
    end = db.one("SELECT close FROM bars WHERE instrument_id=? AND date<=? ORDER BY date DESC LIMIT 1", (bench, end_date))
    if not start or not end:
        return None
    return end["close"] / start["close"] - 1


def _close(rec: dict, exit_price: float, reason: str, end_date: str | None = None) -> None:
    end_date = end_date or db.today()
    realized = _ret(rec["direction"], rec["entry_price"], exit_price)
    bench = _benchmark_return(rec, end_date)
    db.execute(
        """UPDATE recommendations SET status='closed', closed_at=?, exit_price=?, exit_reason=?, realized_return=?,
           benchmark_return=?, excess_return=? WHERE id=?""",
        (db.now_iso(), exit_price, reason, realized, bench, realized - bench if bench is not None else None, rec["id"]),
    )
    live.publish("recommendations")


def score_open() -> dict:
    """Mark every open recommendation; close those that hit stop/target or expired."""
    closed = 0
    now = datetime.now(timezone.utc)
    for rec in list_recs("open"):
        bars = db.rows("SELECT date, open, high, low, close FROM bars WHERE instrument_id=? AND date>? ORDER BY date",
                       (rec["instrument_id"], rec["created_at"][:10]))
        outcome = _path_outcome(rec, bars)
        last = bars[-1] if bars else None
        if not outcome and now >= datetime.fromisoformat(rec["expires_at"]) and last:
            outcome = ("horizon", last["close"], last["date"])
        if outcome:
            _close(rec, outcome[1], outcome[0], outcome[2])
            closed += 1
            continue
        quote = prices.quote(rec["instrument_id"])
        mark = quote["price"] if quote and quote["price"] is not None else (last["close"] if last else None)
        if mark:
            db.execute("UPDATE recommendations SET mark_price=?, mark_return=?, marked_at=? WHERE id=?",
                       (mark, _ret(rec["direction"], rec["entry_price"], mark), db.now_iso(), rec["id"]))
    return {"closed": closed, "early_closes_scored": score_early_closes()}


def track_record() -> dict:
    closed = [rec for rec in list_recs("closed", 5000)]
    open_recs = list_recs("open", 500)

    def summarize(items: list[dict]) -> dict:
        if not items:
            return {"n": 0}
        returns = [r["realized_return"] for r in items if r["realized_return"] is not None]
        excess = [r["excess_return"] for r in items if r["excess_return"] is not None]
        wins = [r for r in returns if r > 0]
        brier = [(r["probability"] - (1.0 if (r["realized_return"] or 0) > 0 else 0.0)) ** 2 for r in items]
        n = len(returns)
        mean = sum(returns) / n if n else None
        sd = math.sqrt(sum((x - mean) ** 2 for x in returns) / (n - 1)) if n > 1 else None
        return {
            "n": len(items),
            "hit_rate": len(wins) / n if n else None,
            "avg_return": mean,
            "avg_excess": sum(excess) / len(excess) if excess else None,
            "t_stat": (mean / (sd / math.sqrt(n))) if sd else None,
            "brier": sum(brier) / len(brier),
            "brier_baseline": 0.25,
            "avg_probability": sum(r["probability"] for r in items) / len(items),
            "best": max(returns) if returns else None,
            "worst": min(returns) if returns else None,
        }

    def group(key) -> dict:
        buckets: dict[str, list[dict]] = {}
        for rec in closed:
            for value in key(rec):
                buckets.setdefault(value, []).append(rec)
        return {k: summarize(v) for k, v in sorted(buckets.items())}

    calibration = []
    for low in (0.5, 0.55, 0.6, 0.65, 0.7, 0.8):
        high = {0.5: 0.55, 0.55: 0.6, 0.6: 0.65, 0.65: 0.7, 0.7: 0.8, 0.8: 1.0}[low]
        items = [r for r in closed if low <= r["probability"] < high]
        if items:
            calibration.append({
                "bucket": f"{low:.2f}–{high:.2f}", "n": len(items),
                "stated": sum(r["probability"] for r in items) / len(items),
                "realized": sum(1 for r in items if (r["realized_return"] or 0) > 0) / len(items),
            })
    return {
        "overall": summarize(closed),
        "open": {"n": len(open_recs),
                 "avg_mark_return": (sum(r["mark_return"] or 0 for r in open_recs) / len(open_recs)) if open_recs else None},
        "by_asset_class": group(lambda r: [r["asset_class"]]),
        "by_confidence": group(lambda r: [r["confidence"]]),
        "by_direction": group(lambda r: [r["direction"]]),
        "by_source": group(lambda r: [r["source"]]),
        "by_evidence": group(lambda r: sorted({str(e.get("type", "other")) for e in r["evidence"] if isinstance(e, dict)})),
        "by_exit": group(lambda r: [r["exit_reason"] or "?"]),
        "by_skill": group(lambda r: r["skills"] or ["(no skill)"]),
        "early_closes": _early_close_stats(closed),
        "calibration": calibration,
        "recent": closed[:50],
    }


def _early_close_stats(closed: list[dict]) -> dict:
    """AI early closes vs holding: positive `saved` means closing early helped."""
    items = [r for r in closed if r["exit_reason"] == "ai_review"]
    scored = [r for r in items if r.get("hold_return") is not None and r.get("realized_return") is not None]
    saved = [r["realized_return"] - r["hold_return"] for r in scored]
    return {
        "n": len(items),
        "scored": len(scored),
        "avg_realized": sum(r["realized_return"] for r in scored) / len(scored) if scored else None,
        "avg_if_held": sum(r["hold_return"] for r in scored) / len(scored) if scored else None,
        "avg_saved": sum(saved) / len(saved) if saved else None,
        "helped": sum(1 for s in saved if s > 0),
    }


def lessons() -> str:
    """Compact track-record digest injected into the analyst's prompt."""
    record = track_record()
    overall = record["overall"]
    if not overall.get("n"):
        return "No recommendations have closed yet, so there is no track record to learn from."
    lines = [
        f"Closed recommendations: {overall['n']}, hit rate {overall['hit_rate']:.0%}, "
        f"avg return {overall['avg_return']:+.2%}"
        + (f", avg excess vs benchmark {overall['avg_excess']:+.2%}" if overall.get("avg_excess") is not None else "")
        + f", Brier {overall['brier']:.3f} (0.25 = coin flip), avg stated probability {overall['avg_probability']:.0%}.",
    ]
    for title, key in (("By evidence type", "by_evidence"), ("By asset class", "by_asset_class"),
                       ("By confidence", "by_confidence"), ("By direction", "by_direction"),
                       ("By skill loaded", "by_skill")):
        parts = [f"{name}: n={s['n']} hit {s['hit_rate']:.0%} avg {s['avg_return']:+.2%}"
                 for name, s in record[key].items() if s.get("n", 0) >= 3 and s.get("hit_rate") is not None]
        if parts:
            lines.append(f"{title}: " + "; ".join(parts))
    for row in record["calibration"]:
        if row["n"] >= 5:
            lines.append(f"Calibration {row['bucket']}: stated {row['stated']:.0%} vs realized {row['realized']:.0%} (n={row['n']})")
    early = record["early_closes"]
    if early["scored"]:
        lines.append(f"Your early closes: {early['scored']} scored; closing early {early['avg_saved']:+.2%} per call vs "
                     f"holding ({early['helped']} of {early['scored']} helped).")
    recent = [r for r in record["recent"] if r.get("lesson")][:8]
    if recent:
        lines.append("Recent post-mortems:")
        lines += [f"- {r['symbol']} {r['direction']} ({r['realized_return']:+.1%}): {r['lesson']}" for r in recent
                  if r.get("realized_return") is not None]
    return "\n".join(lines)
