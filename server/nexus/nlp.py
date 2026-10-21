"""LLM headline classification into the event taxonomy (batched, fast model)."""

from __future__ import annotations

import json
import re
import time

from . import db, live, llm, universe
from .taxonomy import NEWS_CATEGORIES

BATCH = 30

SYSTEM = """You tag financial news headlines for a market-research database.
For each headline return: category (one of the allowed list), direction for the
affected assets (-1 bearish, 0 unclear, 1 bullish), magnitude (1 minor, 2 notable,
3 major market-moving), and up to 4 affected instrument ids from the universe list
(only if the headline clearly concerns them; empty list otherwise). Be conservative:
most headlines are "other" with magnitude 1. Return only JSON:
{"items": [{"i": 0, "category": "...", "direction": 0, "magnitude": 1, "affected": ["stock:aapl"], "why": "<=12 words"}]}"""


def _universe_hint() -> str:
    return ", ".join(f"{item.id}={item.symbol}" for item in universe.INSTRUMENTS if item.tradable)


def _parse(text: str) -> list[dict]:
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        return []
    try:
        return json.loads(match.group()).get("items", [])
    except json.JSONDecodeError:
        return []


def classify_pending(limit: int = 300, days: int = 3, deadline_s: float | None = None) -> dict:
    started = time.monotonic()
    pending = db.rows(
        """SELECT id, title, summary, tickers FROM news WHERE classified_at IS NULL AND duplicate_of IS NULL
           AND published_at >= datetime('now', ?) ORDER BY published_at DESC LIMIT ?""",
        (f"-{days} days", limit),
    )
    if not pending:
        return {"classified": 0}
    provider = llm.create("fast")
    categories = ", ".join(NEWS_CATEGORIES)
    hint = _universe_hint()
    classified = 0
    for offset in range(0, len(pending), BATCH):
        if deadline_s is not None and time.monotonic() - started > deadline_s:
            break
        batch = pending[offset:offset + BATCH]
        listing = "\n".join(
            f"{i}. {row['title']}" + (f" — {row['summary'][:160]}" if row["summary"] else "")
            + (f" [tagged: {', '.join(db.loads(row['tickers'], []))}]" if row["tickers"] else "")
            for i, row in enumerate(batch)
        )
        prompt = f"Allowed categories: {categories}\n\nUniverse: {hint}\n\nHeadlines:\n{listing}"
        try:
            reply = provider.complete(SYSTEM, [{"role": "user", "text": prompt}], max_tokens=8000, effort="low")
        except Exception as exc:
            db.log("warn", "classify", f"LLM call failed: {exc}")
            break
        results = {int(item.get("i", -1)): item for item in _parse(reply.text) if isinstance(item, dict)}
        updates = []
        for i, row in enumerate(batch):
            item = results.get(i)
            if not item:
                continue
            category = item.get("category") if item.get("category") in NEWS_CATEGORIES else "other"
            affected = [a for a in (item.get("affected") or []) if universe.get(str(a))][:4]
            tickers = db.loads(row["tickers"], []) or []
            updates.append((
                category, _clamp(item.get("direction"), -1, 1), _clamp(item.get("magnitude"), 1, 3),
                db.dumps(sorted(set(affected) | set(t for t in tickers if universe.get(t)))),
                str(item.get("why", ""))[:200], db.now_iso(), row["id"],
            ))
        db.executemany(
            "UPDATE news SET category=?, direction=?, magnitude=?, affected=?, rationale=?, classified_at=? WHERE id=?",
            updates,
        )
        classified += len(updates)
        if updates:
            live.publish("news")
    return {"classified": classified}


def _clamp(value, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return 0 if low < 0 else low


def recent(instrument_id: str | None = None, days: int = 7, limit: int = 40, min_magnitude: int = 1,
           category: str | None = None) -> list[dict]:
    sql = "SELECT * FROM news WHERE published_at >= datetime('now', ?) AND duplicate_of IS NULL"
    params: list = [f"-{days} days"]
    if instrument_id:
        sql += " AND (affected LIKE ? OR tickers LIKE ?)"
        params += [f'%"{instrument_id}"%', f'%"{instrument_id}"%']
    if min_magnitude > 1:
        sql += " AND magnitude >= ?"
        params.append(min_magnitude)
    if category:
        sql += " AND category = ?"
        params.append(category)
    rows = db.rows(sql + " ORDER BY published_at DESC LIMIT ?", params + [limit])
    for row in rows:
        row["affected"] = db.loads(row.get("affected"), [])
        row["tickers"] = db.loads(row.get("tickers"), [])
        row["historical_analogs"] = NEWS_CATEGORIES.get(row.get("category") or "", [])
    return rows
