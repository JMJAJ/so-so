"""Housekeeping: keep the database (and so every snapshot push and restore) from filling up
with rows nothing reads any more, without touching anything the research or the record needs.

Removed, because no code path can reach them once they are this old:
  logs            older than LOG_DAYS, and beyond the newest LOG_MAX_ROWS (the UI shows 1000)
  notifications   older than NOTIFY_DAYS (their keys stop repeats of a day's or story's alert;
                  nothing that old can come round again)
  news duplicates older than DUPLICATE_DAYS (hidden everywhere already; the dedupe window is 48 h,
                  and dropping them never changes which rows count as originals)
  news            older than the `news_retention_days` setting (default 730; 0 keeps everything).
                  Every reader looks back at most 400 days (news page 365, backfill dedupe 400).

Compacted, nothing lost:
  runs.transcript of runs finished more than TRANSCRIPT_PACK_DAYS ago is stored zlib-compressed
  (`db.loads` reads both forms), so the AI's reasoning trail stays available.

Never touched: prices, macro, events, GDELT themes, research tables, recommendations, positions,
trades, equity history, accounts, chats, settings, runs themselves.
"""

from __future__ import annotations

import zlib
from datetime import datetime, timedelta, timezone

from . import config, db, memory

LOG_DAYS = 30
LOG_MAX_ROWS = 20_000
NOTIFY_DAYS = 90
DUPLICATE_DAYS = 14
TRANSCRIPT_PACK_DAYS = 14
MIN_NEWS_DAYS = 400  # the longest look-back any feature has; a lower setting is raised to this
VACUUM_FREE_SHARE = 0.25


def _cutoff(days: int, now: datetime) -> str:
    return (now - timedelta(days=days)).isoformat(timespec="seconds")


def run(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    result: dict = {}
    with db.session() as conn:
        result["logs"] = conn.execute("DELETE FROM logs WHERE created_at < ?", (_cutoff(LOG_DAYS, now),)).rowcount
        result["logs"] += conn.execute(
            "DELETE FROM logs WHERE id <= (SELECT id FROM logs ORDER BY id DESC LIMIT 1 OFFSET ?)",
            (LOG_MAX_ROWS,)).rowcount
        result["notifications"] = conn.execute(
            "DELETE FROM notifications WHERE created_at < ?", (_cutoff(NOTIFY_DAYS, now),)).rowcount
        result["news_duplicates"] = conn.execute(
            "DELETE FROM news WHERE duplicate_of IS NOT NULL AND published_at < ?",
            (_cutoff(DUPLICATE_DAYS, now),)).rowcount
        keep = config.get_int("news_retention_days")
        result["news_old"] = 0
        if keep > 0:
            result["news_old"] = conn.execute(
                "DELETE FROM news WHERE published_at < ?", (_cutoff(max(keep, MIN_NEWS_DAYS), now),)).rowcount
        packed = 0
        for row in conn.execute(
                "SELECT id, transcript FROM runs WHERE finished_at < ? AND typeof(transcript) = 'text'",
                (_cutoff(TRANSCRIPT_PACK_DAYS, now),)).fetchall():
            conn.execute("UPDATE runs SET transcript=? WHERE id=?",
                         (zlib.compress(row["transcript"].encode("utf-8"), 6), row["id"]))
            packed += 1
        result["transcripts_packed"] = packed
    result["sqlite"] = _maintain()
    sweep_memory()
    return result


def _maintain() -> dict:
    """Return space to the file system and keep the query planner's statistics current."""
    out: dict = {}
    conn = db.connect()  # its own connection: VACUUM cannot run inside a pooled transaction
    try:
        pages = conn.execute("PRAGMA page_count").fetchone()[0]
        free = conn.execute("PRAGMA freelist_count").fetchone()[0]
        out["free_share"] = round(free / pages, 3) if pages else 0.0
        if pages and free / pages > VACUUM_FREE_SHARE:
            try:
                conn.execute("VACUUM")
                out["vacuumed"] = True
            except Exception as exc:  # noqa: BLE001 — busy right now: next run tries again
                out["vacuumed"] = f"skipped: {exc}"
        conn.execute("PRAGMA optimize")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    return out


def sweep_memory() -> None:
    """Drop expired in-process cache entries (each cache also sweeps itself as it fills)."""
    from . import auth, data
    from .ingest import prices

    data.sweep()
    prices.sweep_intraday()
    auth.sweep()
    memory.trim()
