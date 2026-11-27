"""Universe scan: today's forecast for every tradable instrument, cached between runs."""

from __future__ import annotations

import threading
import time

from .. import config, db, live, memory, nlp
from . import event_study, signals

TTL = 6 * 3600
_lock = threading.Lock()
_cache: dict = {"at": 0.0, "rows": []}
# The last finished scan is also kept in the database (and so in the deploy snapshot): a restart
# serves it at once instead of making the first page wait for a universe-wide recompute.
CACHE_KEY = "forecasts"


def _restore() -> None:
    """Load the persisted scan into memory when this process has none yet."""
    if _cache["rows"]:
        return
    try:
        row = db.one("SELECT at, payload FROM cache WHERE key=?", (CACHE_KEY,))
    except Exception:  # noqa: BLE001 — no table yet (an old snapshot): compute as before
        return
    rows = db.loads(row["payload"], []) if row else []
    if rows and not _cache["rows"]:
        _cache.update(at=float(row["at"]), rows=rows)


def _persist(rows: list[dict], at: float) -> None:
    try:
        db.execute("INSERT OR REPLACE INTO cache(key, at, payload) VALUES(?,?,?)", (CACHE_KEY, at, db.dumps(rows)))
    except Exception as exc:  # noqa: BLE001 — the in-memory rows still serve this process
        db.log("warn", "scan", f"could not persist forecasts: {exc}")


def forecasts(*, refresh: bool = False, progress=None, wait: bool = True) -> list[dict]:
    """Forecast rows for the tradable universe. Readers never wait on a recompute: they get the
    last finished rows at once (a stale cache refreshes in the background). Only a caller that
    asks for `refresh` (jobs, the analyst), or the very first call, waits for a computation.
    With `wait=False` even the first call returns at once (empty) and computes in the background:
    page requests that only show one row must not hold for a universe-wide scan."""
    _restore()
    rows = _cache["rows"]
    if not rows and not refresh and not wait:
        if not _lock.locked():
            threading.Thread(target=_recompute, daemon=True, name="forecasts").start()
        return []
    if rows and not refresh:
        if time.time() - _cache["at"] >= TTL and not _lock.locked():
            threading.Thread(target=_recompute, daemon=True, name="forecasts").start()
        return rows
    asked = time.time()
    with _lock:
        # Someone else may have finished a computation while this call waited for the lock:
        # use it instead of computing the same thing twice in a row.
        if _cache["rows"] and (not refresh or _cache["at"] >= asked):
            return _cache["rows"]
        return _compute(progress)


def mark_stale() -> None:
    """Recompute on the next read (in the background), not now."""
    _cache["at"] = 0.0
    try:
        db.execute("UPDATE cache SET at=0 WHERE key=?", (CACHE_KEY,))
    except Exception:  # noqa: BLE001
        pass


def _recompute() -> None:
    if not _lock.acquire(blocking=False):
        return
    try:
        _compute(None)
    except Exception as exc:  # a failed background refresh keeps serving the old rows
        db.log("warn", "scan", f"background refresh failed: {exc}")
    finally:
        _lock.release()


def _compute(progress) -> list[dict]:
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
    at = time.time()
    _cache.update(at=at, rows=rows)
    _persist(rows, at)
    memory.trim()
    db.log("info", "scan", f"Scanned {len(rows)} instruments")
    live.publish("forecasts")
    return rows


def ranked(asset_class: str | None = None, direction: str = "both", limit: int = 15, *,
           wait: bool = True) -> list[dict]:
    rows = forecasts(wait=wait)
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
