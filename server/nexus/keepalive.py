"""Keep a Render free service awake by pinging its own public URL.

Render spins a free web service down after 15 minutes without inbound requests, which would
also stop the scheduler. A request to our own public URL goes out through Render's front
door and counts as inbound, so a ping every KEEPALIVE_MINUTES (default 10) keeps it up.

It only runs where Render sets RENDER_EXTERNAL_URL (never locally); KEEPALIVE_MINUTES=0
turns it off. It can't wake the service after a crash or restart that leaves it down, so an
external pinger (cron-job.org) on /api/health remains a useful backup.
"""

from __future__ import annotations

import os
import threading

import requests

from . import db

_stop = threading.Event()
_thread: threading.Thread | None = None
_state: dict = {"last_ping": None, "last_error": None}


def target() -> str | None:
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    return f"{base}/api/health" if base else None


def interval_minutes() -> float:
    try:
        return float(os.environ.get("KEEPALIVE_MINUTES", "10"))
    except ValueError:
        return 10.0


def enabled() -> bool:
    return bool(target()) and interval_minutes() > 0


def ping() -> bool:
    url = target()
    if not url:
        return False
    try:
        requests.get(url, timeout=30).raise_for_status()
    except requests.RequestException as exc:
        if _state["last_error"] is None:  # log the first failure, not every one
            db.log("warn", "keepalive", f"self-ping failed: {exc}")
        _state["last_error"] = str(exc)
        return False
    _state.update(last_ping=db.now_iso(), last_error=None)
    return True


def _run() -> None:
    while not _stop.wait(interval_minutes() * 60):
        ping()


def start() -> None:
    global _thread
    if not enabled() or (_thread and _thread.is_alive()):
        return
    _stop.clear()
    _thread = threading.Thread(target=_run, daemon=True, name="keepalive")
    _thread.start()


def stop() -> None:
    _stop.set()


def status() -> dict:
    return {"enabled": enabled(), **_state}
