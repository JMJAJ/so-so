"""Universe scan: today's forecast for every tradable instrument, cached between runs."""

from __future__ import annotations

import threading
import time

from .. import config, db, nlp
from . import event_study, signals

TTL = 6 * 3600
_lock = threading.Lock()
_cache: dict = {"at": 0.0, "rows": []}


def forecasts(*, refresh: bool = False, progress=None) -> list[dict]:
    with _lock:
        if not refresh and _cache["rows"] and time.time() - _cache["at"] < TTL:
            return _cache["rows"]
        enabled = [c.strip() for c in config.get("enabled_classes").split(",") if c.strip()]
        from .. import universe

        ids = [item.id for item in universe.tradable(enabled)]
        rows = signals.predict(ids, progress=progress)
        recent = event_study.recent_events(days=7)
        for row in rows:
            row["recent_events"] = [
                event["type"] for event in recent
                if event["instrument_id"] in (None, row["instrument_id"])
            ][:6]
            news = nlp.recent(row["instrument_id"], days=3, limit=10, min_magnitude=2)
            row["news_flow"] = sum((n.get("direction") or 0) * (n.get("magnitude") or 0) for n in news)
            row["news_count"] = len(news)
        _cache.update(at=time.time(), rows=rows)
        db.log("info", "scan", f"Scanned {len(rows)} instruments")
        return rows


def ranked(asset_class: str | None = None, direction: str = "both", limit: int = 15) -> list[dict]:
    rows = forecasts()
    if asset_class:
        rows = [r for r in rows if r["asset_class"] == asset_class]
    if direction == "long":
        rows = [r for r in rows if (r.get("expected_return") or 0) > 0]
    elif direction == "short":
        rows = [r for r in rows if (r.get("expected_return") or 0) < 0]
    rows = [r for r in rows if r.get("stale_days", 0) <= 5]
    return sorted(rows, key=lambda r: -interest(r))[:limit]


def interest(row: dict) -> float:
    """How much there is to look at. With a validated model, its risk-adjusted forecast;
    without one, the strength of the event/analog evidence plus classified news flow."""
    news = 0.15 * abs(row.get("news_flow") or 0)
    if row.get("model_has_edge"):
        return abs(row.get("score") or 0) + news
    sig = row.get("signals") or {}
    return 0.5 * (abs(sig.get("analog") or 0) + abs(sig.get("event") or 0)) + news
