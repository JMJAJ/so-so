"""Keep the SQLite database alive on hosts with a throwaway disk (Render free tier).

When SUPABASE_URL and SUPABASE_SERVICE_KEY are set, the database is copied to Supabase
Storage as a gzipped snapshot:
  - on startup, if there is no local database yet, the latest snapshot is downloaded;
  - every SNAPSHOT_MINUTES, if the database changed, and after every job;
  - on shutdown (Render sends SIGTERM before restarts and deploys).
One dated copy per day is also kept (the last KEEP_DAILY days) to roll back from.
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

_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_state: dict = {"last_push": None, "last_error": None, "last_change": None, "restored_from": None}


def _config() -> tuple[str, str, str] | None:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return None
    return url, key, os.environ.get("SNAPSHOT_BUCKET", "nexus")


def enabled() -> bool:
    return _config() is not None


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
            with open(copy, "rb") as src, gzip.open(packed, "wb", compresslevel=6) as dst:
                shutil.copyfileobj(src, dst)
            names = [LATEST, f"{DAILY_PREFIX}{date.today().isoformat()}.db.gz"]
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


def push_if_changed(reason: str) -> dict | None:
    if not enabled() or _db_mtime() == _state["last_change"]:
        return None
    return push(reason)


def push_async(reason: str) -> None:
    if enabled():
        threading.Thread(target=push_if_changed, args=(reason,), daemon=True, name="snapshot-push").start()


def _run() -> None:
    while not _stop.wait(SNAPSHOT_MINUTES * 60):
        try:
            push_if_changed("periodic")
        except Exception as exc:  # never let the snapshot thread die
            _state["last_error"] = str(exc)


def start() -> None:
    global _thread
    if not enabled() or (_thread and _thread.is_alive()):
        return
    _state["last_change"] = _db_mtime() if _state["restored_from"] else None
    _stop.clear()
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
