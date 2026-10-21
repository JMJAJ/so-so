"""Live updates for the UI: change notifications streamed as server-sent events.

Anything that changes what a page shows calls `publish(topic, ...)`: a job starting or
finishing, an order filling, a recommendation being recorded, new headlines. The UI
listens on /api/live and refetches only what the topic touches.

While a browser is connected, a ticker keeps prices moving: every TICK seconds it
refreshes quotes for open and pending positions and for assets someone is viewing, and
publishes the ones whose price changed. It also runs the paper monitor once a minute
so pending orders fill and stops trigger as soon as the market allows.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from . import db

TICK = 20
MONITOR_EVERY = 60
WATCH_TTL = 180
_HISTORY = 500

_cond = threading.Condition()
_events: deque[dict] = deque(maxlen=_HISTORY)
_seq = 0
_clients = 0
_watched: dict[str, float] = {}
_last_prices: dict[str, float] = {}
_ticker: threading.Thread | None = None
_stop = threading.Event()


def publish(topic: str, **data) -> None:
    global _seq
    with _cond:
        _seq += 1
        _events.append({"seq": _seq, "topic": topic, "at": db.now_iso(), **data})
        _cond.notify_all()


def current_seq() -> int:
    with _cond:
        return _seq


def wait(after: int, timeout: float) -> list[dict]:
    """Events with seq > `after`, waiting up to `timeout` seconds for the first one."""
    with _cond:
        _cond.wait_for(lambda: _seq > after, timeout=timeout)
        return [e for e in _events if e["seq"] > after]


def connected(delta: int) -> None:
    global _clients
    with _cond:
        _clients = max(0, _clients + delta)


def watch(instrument_id: str) -> None:
    """Keep this instrument's quote live for a few minutes (an asset page is open)."""
    _watched[instrument_id] = time.time() + WATCH_TTL


def _live_ids() -> list[str]:
    now = time.time()
    for iid, until in list(_watched.items()):
        if until < now:
            _watched.pop(iid, None)
    held = [row["instrument_id"] for row in db.rows("SELECT DISTINCT instrument_id FROM positions")]
    return sorted(set(held) | set(_watched))


def tick() -> None:
    from .ingest import prices

    ids = _live_ids()
    if not ids:
        return
    changed = {}
    for iid, quote in prices.quotes(ids).items():
        price = quote.get("price")
        if price is not None and _last_prices.get(iid) != price:
            _last_prices[iid] = price
            changed[iid] = {"price": price, "change_pct": quote.get("change_pct"), "as_of": quote.get("as_of")}
    if changed:
        publish("quotes", quotes=changed)


def _run() -> None:
    from . import paper

    last_monitor = 0.0
    while not _stop.wait(TICK):
        if not _clients:
            continue
        try:
            tick()
            if time.time() - last_monitor >= MONITOR_EVERY:
                last_monitor = time.time()
                paper.monitor()
        except Exception as exc:  # a failed quote fetch must not kill the ticker
            db.log("warn", "live", f"ticker: {exc}")


def start() -> None:
    global _ticker
    if _ticker and _ticker.is_alive():
        return
    _stop.clear()
    _ticker = threading.Thread(target=_run, daemon=True, name="live-ticker")
    _ticker.start()


def stop() -> None:
    _stop.set()
