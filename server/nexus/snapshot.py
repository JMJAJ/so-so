"""Keep the SQLite database alive on hosts with a throwaway disk (Render free tier).

When SUPABASE_URL and SUPABASE_SERVICE_KEY are set, the database is copied to Supabase
Storage as a gzipped snapshot:
  - on startup, if there is no local database yet, the latest snapshot is downloaded;
  - every SNAPSHOT_MINUTES, if the database changed, and after every job;
  - on shutdown (Render sends SIGTERM before restarts and deploys).
One dated copy per day is also kept (the last KEEP_DAILY days) to roll back from: the first
push of each day, so a later bad state never overwrites that day's restore point.

Supabase pauses free projects after a week without database activity, and it's not documented
whether Storage traffic counts. So on startup and then at most every HEARTBEAT_HOURS the server
also upserts one row into a `nexus_heartbeat` table, a definite database write (see DEPLOY.md).
Copies are made with SQLite's backup API, so they are consistent while the app writes.
"""

from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from datetime import date, timedelta

import requests

from . import db

LATEST = "nexus_v3.db.gz"
DAILY_PREFIX = "daily/"
KEEP_DAILY = 7
SNAPSHOT_MINUTES = float(os.environ.get("SNAPSHOT_MINUTES", "15"))
HEARTBEAT_TABLE = "nexus_heartbeat"
HEARTBEAT_HOURS = 6

_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_state: dict = {"last_push": None, "last_error": None, "last_change": None, "restored_from": None,
                "last_heartbeat": None, "heartbeat_error": None}
_last_beat = 0.0


def _config() -> tuple[str, str, str] | None:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return None
    return url, key, os.environ.get("SNAPSHOT_BUCKET", "nexus")


def enabled() -> bool:
    return _config() is not None


def read_only() -> bool:
    """A pulled copy that must never be pushed back (GitHub Actions research runs): pushing it
    would overwrite whatever the live server recorded since the copy was taken."""
    return os.environ.get("NEXUS_SNAPSHOT_READONLY", "").lower() in ("1", "true", "yes")


def _headers(key: str, **extra: str) -> dict:
    return {"Authorization": f"Bearer {key}", "apikey": key, **extra}


def _object_url(name: str) -> str:
    url, _, bucket = _config()  # type: ignore[misc]
    return f"{url}/storage/v1/object/{bucket}/{name}"


def pull(force: bool = False) -> bool:
    """Download the latest snapshot into DB_PATH. Without `force`, only when no local database exists."""
    config = _config()
    if not config or (os.path.exists(db.DB_PATH) and not force):
        return False
    _, key, _ = config
    response = requests.get(_object_url(LATEST), headers=_headers(key), timeout=120, stream=True)
    if response.status_code in (400, 404):
        return False  # no snapshot yet: start fresh
    response.raise_for_status()
    os.makedirs(os.path.dirname(db.DB_PATH), exist_ok=True)
    tmp = db.DB_PATH + ".download"
    with open(tmp, "wb") as raw:
        for chunk in response.iter_content(1 << 20):
            raw.write(chunk)
    with gzip.open(tmp, "rb") as src, open(db.DB_PATH + ".restore", "wb") as dst:
        shutil.copyfileobj(src, dst)
    os.remove(tmp)
    db.close_all()  # pooled connections must not keep the old file open
    for suffix in ("-wal", "-shm"):
        if os.path.exists(db.DB_PATH + suffix):
            os.remove(db.DB_PATH + suffix)
    os.replace(db.DB_PATH + ".restore", db.DB_PATH)
    _state["restored_from"] = LATEST
    return True


def _db_mtime() -> float:
    return max((os.path.getmtime(p) for p in (db.DB_PATH, db.DB_PATH + "-wal") if os.path.exists(p)), default=0.0)


def push(reason: str = "manual") -> dict:
    """Upload a consistent gzipped copy of the database (and today's dated copy)."""
    config = _config()
    if read_only():
        return {"pushed": False, "reason": "read-only copy (NEXUS_SNAPSHOT_READONLY)"}
    if not config or not os.path.exists(db.DB_PATH):
        return {"pushed": False, "reason": "snapshots not configured" if not config else "no database"}
    _, key, _ = config
    with _lock:
        changed_at = _db_mtime()
        with tempfile.TemporaryDirectory() as tmp:
            copy = os.path.join(tmp, "copy.db")
            source = sqlite3.connect(db.DB_PATH, timeout=30)
            target = sqlite3.connect(copy)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            packed = os.path.join(tmp, LATEST)
            # Level 1: half the CPU of level 6 for a ~5% larger file; on a shared fraction of a
            # core the CPU is what every page request competes with.
            with open(copy, "rb") as src, gzip.open(packed, "wb", compresslevel=1) as dst:
                shutil.copyfileobj(src, dst)
            today = date.today().isoformat()
            daily = _state.get("daily_pushed") != today
            names = [LATEST] + ([f"{DAILY_PREFIX}{today}.db.gz"] if daily else [])
            try:
                for name in names:
                    with open(packed, "rb") as body:
                        response = requests.post(_object_url(name), data=body, timeout=300,
                                                 headers=_headers(key, **{"x-upsert": "true",
                                                                          "Content-Type": "application/gzip"}))
                    response.raise_for_status()
                size = os.path.getsize(packed)
            except requests.RequestException as exc:
                _state["last_error"] = f"{reason}: {exc}"
                db.log("warn", "snapshot", f"push failed ({reason}): {exc}")
                return {"pushed": False, "error": str(exc)}
        _state.update(last_push=db.now_iso(), last_error=None, last_change=changed_at)
        if daily:
            _state["daily_pushed"] = today
    heartbeat()
    if daily:
        _prune_daily(key)
    return {"pushed": True, "bytes": size, "reason": reason}


def _prune_daily(key: str) -> None:
    url, _, bucket = _config()  # type: ignore[misc]
    try:
        listing = requests.post(f"{url}/storage/v1/object/list/{bucket}", headers=_headers(key), timeout=30,
                                json={"prefix": DAILY_PREFIX.rstrip("/"), "limit": 100})
        listing.raise_for_status()
        cutoff = (date.today() - timedelta(days=KEEP_DAILY)).isoformat()
        old = [f"{DAILY_PREFIX}{item['name']}" for item in listing.json() if item.get("name", "") < cutoff]
        if old:
            requests.delete(f"{url}/storage/v1/object/{bucket}", headers=_headers(key), json={"prefixes": old},
                            timeout=30)
    except (requests.RequestException, ValueError):
        pass  # pruning is best effort


def heartbeat(force: bool = False) -> bool:
    """Upsert the single heartbeat row (keeps a free Supabase project from pausing)."""
    global _last_beat
    config = _config()
    if not config or (not force and time.monotonic() - _last_beat < HEARTBEAT_HOURS * 3600 and _last_beat):
        return False
    url, key, _ = config
    try:
        response = requests.post(
            f"{url}/rest/v1/{HEARTBEAT_TABLE}", timeout=30,
            headers=_headers(key, **{"Content-Type": "application/json",
                                     "Prefer": "resolution=merge-duplicates,return=minimal"}),
            json={"id": 1, "beat_at": db.now_iso(), "note": "nexus snapshot"},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        if _state["heartbeat_error"] is None:  # log once, not every tick
            db.log("warn", "snapshot", f"heartbeat failed (did you create the {HEARTBEAT_TABLE} table?): {exc}")
        _state["heartbeat_error"] = str(exc)
        return False
    _last_beat = time.monotonic()
    _state.update(last_heartbeat=db.now_iso(), heartbeat_error=None)
    return True


def push_if_changed(reason: str) -> dict | None:
    if not enabled() or _db_mtime() == _state["last_change"]:
        return None
    return push(reason)


def push_async(reason: str) -> None:
    if enabled() and not read_only():
        threading.Thread(target=push_if_changed, args=(reason,), daemon=True, name="snapshot-push").start()


def _run() -> None:
    while not _stop.wait(SNAPSHOT_MINUTES * 60):
        try:
            push_if_changed("periodic")
            heartbeat()
        except Exception as exc:  # never let the snapshot thread die
            _state["last_error"] = str(exc)


def start() -> None:
    global _thread
    if not enabled() or (_thread and _thread.is_alive()):
        return
    _state["last_change"] = _db_mtime() if _state["restored_from"] else None
    _stop.clear()
    threading.Thread(target=heartbeat, kwargs={"force": True}, daemon=True, name="heartbeat").start()
    _thread = threading.Thread(target=_run, daemon=True, name="snapshot")
    _thread.start()


def stop() -> None:
    _stop.set()
    if enabled():
        started = time.monotonic()
        push_if_changed("shutdown")
        db.log("info", "snapshot", f"shutdown snapshot in {time.monotonic() - started:.1f}s")


def status() -> dict:
    return {"enabled": enabled(), **_state}
