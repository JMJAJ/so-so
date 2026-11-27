"""Housekeeping removes only what nothing reads, and keeps everything the record needs."""

import time
from datetime import datetime, timedelta, timezone

from nexus import auth, cleanup, config, data, db
from nexus.ingest import prices

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)


def ago(days: float) -> str:
    return (NOW - timedelta(days=days)).isoformat(timespec="seconds")


def add_news(news_id: str, days: float, duplicate_of: str | None = None) -> None:
    db.execute("INSERT INTO news(id, published_at, title, provider, duplicate_of) VALUES(?,?,?,?,?)",
               (news_id, ago(days), f"headline {news_id}", "wire", duplicate_of))


def ids(sql: str) -> set[str]:
    return {str(next(iter(row.values()))) for row in db.rows(sql)}


def test_cleanup_prunes_only_unreachable_rows(nexus_db):
    for days, message in ((40, "old"), (5, "recent")):
        db.execute("INSERT INTO logs(created_at, level, kind, message) VALUES(?,?,?,?)",
                   (ago(days), "info", "test", message))
    for days, key in ((120, "old"), (10, "recent")):
        db.execute("INSERT INTO notifications(key, created_at, kind, title, message, priority, status) "
                   "VALUES(?,?,?,?,?,?,?)", (key, ago(days), "move", "t", "m", 3, "sent"))
    add_news("original-old", 30)
    add_news("dup-old", 30, duplicate_of="original-old")
    add_news("original-new", 2)
    add_news("dup-new", 2, duplicate_of="original-new")
    add_news("year-old", 380)  # inside every look-back: kept even with a short retention setting
    add_news("ancient", 800)
    transcript = [{"role": "assistant", "content": "why I bought gold " * 50}]
    db.execute("INSERT INTO runs(id, kind, started_at, finished_at, status, transcript) VALUES(?,?,?,?,?,?)",
               ("run-old", "analyst", ago(30), ago(30), "completed", db.dumps(transcript)))
    db.execute("INSERT INTO runs(id, kind, started_at, finished_at, status, transcript) VALUES(?,?,?,?,?,?)",
               ("run-new", "analyst", ago(1), ago(1), "completed", db.dumps(transcript)))

    result = cleanup.run(now=NOW)

    assert ids("SELECT message FROM logs WHERE kind='test'") == {"recent"}
    assert ids("SELECT key FROM notifications") == {"recent"}
    assert ids("SELECT id FROM news") == {"original-old", "original-new", "dup-new", "year-old"}
    assert result["news_duplicates"] == 1 and result["news_old"] == 1
    # Old transcripts are compressed, not dropped, and still read back in full.
    assert result["transcripts_packed"] == 1
    kinds = {r["id"]: r["t"] for r in db.rows("SELECT id, typeof(transcript) t FROM runs")}
    assert kinds == {"run-old": "blob", "run-new": "text"}
    for run_id in ("run-old", "run-new"):
        stored = db.one("SELECT transcript FROM runs WHERE id=?", (run_id,))["transcript"]
        assert db.loads(stored) == transcript
    assert cleanup.run(now=NOW)["transcripts_packed"] == 0  # idempotent


def test_news_retention_never_drops_below_what_readers_need(nexus_db):
    add_news("year-old", 380)
    add_news("ancient", 800)
    config.set_many({"news_retention_days": "30"})  # too short: raised to MIN_NEWS_DAYS
    cleanup.run(now=NOW)
    assert ids("SELECT id FROM news") == {"year-old"}
    config.set_many({"news_retention_days": "0"})  # 0 keeps every headline
    add_news("ancient", 800)
    cleanup.run(now=NOW)
    assert ids("SELECT id FROM news") == {"year-old", "ancient"}


def test_caches_drop_expired_entries(nexus_db, monkeypatch):
    data.invalidate()
    data._cached(("short",), lambda: 1, ttl=0.01)
    data._cached(("long",), lambda: 2, ttl=3600)
    time.sleep(0.02)
    assert data.sweep() == 1
    assert ("short",) not in data._cache and ("long",) in data._cache
    assert ("short",) not in data._loading

    prices._intraday.clear()
    prices._intraday[("etf:spy", "1d")] = (time.time() - prices.INTRADAY_KEEP - 1, [])
    prices._intraday[("etf:qqq", "1d")] = (time.time(), [])
    prices.sweep_intraday()
    assert list(prices._intraday) == [("etf:qqq", "1d")]

    auth._failures.clear()
    auth._failures["1.2.3.4"] = [time.time() - auth.LOCKOUT_SECONDS - 1]
    auth._failures["5.6.7.8"] = [time.time()]
    auth.sweep()
    assert list(auth._failures) == ["5.6.7.8"]
