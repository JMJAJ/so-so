"""Push notifications to your phone through ntfy (https://ntfy.sh).

Install the ntfy app, subscribe to your topic, and save the same topic in Settings (or set
NTFY_TOPIC). What gets pushed:

- breaking news from the wire at `notify_news_level` or above, plus major alerts about any
  asset you watch, hold or the AI has an open call on;
- abnormal price moves on those assets, measured in the asset's own daily volatility (σ),
  so a 3% day is news for SPY but not for a small crypto;
- every new AI call (buy or sell, with the server-computed probability and EV) and every paper
  position closed by its stop, target or horizon.

A top alert or a big move on a watched asset can also start a focused analyst run, whose calls
then arrive as notifications of their own. Each event notifies once (the `key` column).
"""

from __future__ import annotations

import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

from . import config, db, universe

# Market context always watched (the ticker tape's core list).
CORE = ["etf:spy", "etf:qqq", "index:vix", "index:tnx", "crypto:btc", "commodity:wti", "commodity:gold",
        "forex:eurusd"]
MAX_NEWS_PER_HOUR = 8
AUTO_ANALYST_EVERY_S = 3 * 3600
_last_auto = {"at": 0.0}
_lock = threading.Lock()


# ── Settings ─────────────────────────────────────────────────────────────────

def topic() -> str:
    return config.secret("ntfy_topic").strip()


def enabled() -> bool:
    return bool(topic())


def public_url() -> str:
    """The site you open (the Vercel frontend), not the API: Render's own URL serves no pages."""
    return (config.get("public_url") or os.environ.get("NEXUS_PUBLIC_URL", "")).rstrip("/")


def asset_link(instrument_id: str) -> str | None:
    base = public_url()
    return f"{base}/?v=asset&id={instrument_id}" if base else None


def watchlist() -> list[str]:
    ids = []
    for value in config.get("watchlist").split(","):
        item = universe.resolve(value.strip()) if value.strip() else None
        if item and item.id not in ids:
            ids.append(item.id)
    return ids


def set_watchlist(ids: list[str]) -> list[str]:
    clean = []
    for value in ids:
        item = universe.resolve(str(value).strip())
        if item and item.id not in clean:
            clean.append(item.id)
    config.set_many({"watchlist": ",".join(clean)})
    return clean


def watched_ids() -> set[str]:
    """Assets you care about: watchlist, held in any account, or with an open AI call."""
    ids = set(watchlist())
    ids |= {r["instrument_id"] for r in db.rows("SELECT DISTINCT instrument_id FROM positions")}
    ids |= {r["instrument_id"] for r in db.rows("SELECT instrument_id FROM recommendations WHERE status='open'")}
    return ids


# ── Sending ──────────────────────────────────────────────────────────────────

def send(key: str, kind: str, title: str, message: str, *, priority: int = 3, tags: list[str] | None = None,
         click: str | None = None, actions: list[dict] | None = None, wait: bool = False) -> bool:
    """Push once per `key`. Returns False when it was already sent or notifications are off."""
    if not enabled():
        return False
    with _lock:
        if db.one("SELECT 1 FROM notifications WHERE key=?", (key,)):
            return False
        db.execute(
            """INSERT INTO notifications(key,created_at,kind,title,message,priority,click,status)
               VALUES(?,?,?,?,?,?,?,?)""",
            (key, db.now_iso(), kind, title[:250], message[:4000], priority, click, "sending"),
        )
    payload = {"topic": topic(), "title": title[:250], "message": message[:4000], "priority": priority,
               "tags": tags or [], "markdown": False}
    if click:
        payload["click"] = click
    if actions:
        payload["actions"] = actions[:3]

    def deliver() -> None:
        error = None
        try:
            headers = {}
            token = config.secret("ntfy_token").strip()
            if token:
                headers["Authorization"] = f"Bearer {token}"
            server = (config.get("ntfy_server") or "https://ntfy.sh").rstrip("/")
            response = requests.post(server, json=payload, headers=headers, timeout=15)
            if response.status_code >= 300:
                error = f"HTTP {response.status_code}: {response.text[:200]}"
        except Exception as exc:  # network failure: recorded, never raised into the caller
            error = str(exc)[:300]
        db.execute("UPDATE notifications SET status=?, error=? WHERE key=?",
                   ("error" if error else "sent", error, key))
        if error:
            db.log("warn", "notify", f"{title}: {error}")

    if wait:
        deliver()
        row = db.one("SELECT status FROM notifications WHERE key=?", (key,))
        return bool(row and row["status"] == "sent")
    threading.Thread(target=deliver, daemon=True, name="ntfy").start()
    return True


def test() -> dict:
    if not enabled():
        return {"ok": False, "error": "Set an ntfy topic first."}
    key = f"test:{time.time():.0f}"
    ok = send(key, "test", "NEXUS is connected",
              "Notifications work. You'll get breaking news, big moves on your watchlist and every AI buy/sell call.",
              priority=3, tags=["white_check_mark"], click=public_url() or None, wait=True)
    row = db.one("SELECT error FROM notifications WHERE key=?", (key,))
    return {"ok": ok, "error": row["error"] if row else None, "topic": topic()}


def recent(limit: int = 50) -> list[dict]:
    return db.rows("SELECT id, created_at, kind, title, message, priority, click, status, error "
                   "FROM notifications ORDER BY id DESC LIMIT ?", (limit,))


# ── Events ───────────────────────────────────────────────────────────────────

def _symbol(instrument_id: str) -> str:
    item = universe.resolve(instrument_id)
    return item.symbol if item else instrument_id.split(":")[-1].upper()


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:+.1f}%"


def on_alerts(alerts: list[dict]) -> None:
    """Wire alerts that just fired (one per story)."""
    if not enabled() or not alerts:
        return
    level_needed = config.get_int("notify_news_level")
    watched = watched_ids()
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    sent_last_hour = db.one("SELECT COUNT(*) c FROM notifications WHERE kind='news' AND created_at>=?", (since,))["c"]
    for alert in sorted(alerts, key=lambda a: -a["level"]):
        tradable = [t for t in alert["tickers"] if not t.startswith("index:")]
        mine = [t for t in tradable if t in watched]
        top = level_needed > 0 and alert["level"] >= level_needed
        if not (top or (mine and alert["level"] >= 2)):
            continue
        if sent_last_hour >= MAX_NEWS_PER_HOUR and not mine:
            continue
        moves = alert.get("moves") or {}
        lines = [alert["title"]]
        moved = [f"{_symbol(t)} {_pct((moves.get(t) or {}).get('change_pct'))} today" for t in tradable[:4]]
        if moved:
            lines.append(" · ".join(moved))
        lines.append(f"{alert.get('source') or 'wire'} · {', '.join(k.replace('-', ' ') for k in alert['kinds'])}")
        if mine:
            lines.append(f"You follow {', '.join(_symbol(t) for t in mine)}.")
        head = ", ".join(_symbol(t) for t in tradable[:3]) or alert["kinds"][0].replace("-", " ").title()
        actions = []
        if alert.get("url"):
            actions.append({"action": "view", "label": "Read", "url": alert["url"]})
        link = asset_link(tradable[0]) if tradable else public_url() or None
        if link:
            actions.append({"action": "view", "label": "Open NEXUS", "url": link})
        if send(f"news:{alert['id']}", "news", f"{'🚨' if alert['level'] >= 3 else '📰'} {head}", "\n".join(lines),
                priority=4 if alert["level"] >= 3 or mine else 3, tags=["newspaper"],
                click=alert.get("url") or link, actions=actions):
            sent_last_hour += 1
        if alert["level"] >= 3 and ((tradable and not config.get_bool("event_trader"))
                                    or (not tradable and "central-bank" in alert["kinds"])):
            maybe_auto_analyst(f"Breaking news: {alert['title']}" +
                               (f" (affects {', '.join(_symbol(t) for t in tradable[:4])})" if tradable else ""))


def on_call(rec: dict) -> None:
    """A new AI recommendation."""
    if not enabled() or not config.get_bool("notify_calls"):
        return
    symbol = _symbol(rec["instrument_id"])
    side = "BUY" if rec["direction"] == "long" else "SELL / SHORT"
    lines = [f"{side} {symbol} at {rec['entry_price']:.4g} · {rec['horizon_days']} trading days"]
    risk = []
    if rec.get("stop") is not None:
        risk.append(f"stop {rec['stop']:.4g}")
    if rec.get("target") is not None:
        risk.append(f"target {rec['target']:.4g}")
    if risk:
        lines.append(" · ".join(risk))
    stats = []
    if rec.get("probability") is not None:
        stats.append(f"P(win) {rec['probability'] * 100:.0f}%")
    if rec.get("expected_return") is not None:
        stats.append(f"EV {rec['expected_return'] * 100:+.1f}%")
    if stats:
        lines.append(" · ".join(stats))
    if rec.get("thesis"):
        lines.append(rec["thesis"][:400])
    if rec.get("trade_note"):
        lines.append(f"Paper: {rec['trade_note'][:200]}")
    link = asset_link(rec["instrument_id"])
    send(f"call:{rec['id']}", "call", f"{'🟢' if rec['direction'] == 'long' else '🔴'} AI call: {side} {symbol}",
         "\n".join(lines), priority=4, tags=["chart_with_upwards_trend" if rec["direction"] == "long"
                                             else "chart_with_downwards_trend"],
         click=link, actions=[{"action": "view", "label": "Open", "url": link}] if link else None)


def on_exit(position: dict, result: dict) -> None:
    """A paper position closed by its stop, target or horizon."""
    reason = result.get("reason")
    if not enabled() or not config.get_bool("notify_exits") or reason not in ("stop", "target", "horizon"):
        return
    symbol = _symbol(position["instrument_id"])
    entry, exit_price = position["entry_price"], result["exit_price"]
    move = (exit_price / entry - 1) * (1 if position["side"] == "long" else -1) * 100 if entry else None
    account = db.one("SELECT name FROM accounts WHERE id=?", (position.get("account_id"),))
    label = {"stop": "Stop hit", "target": "Target hit", "horizon": "Time's up"}[reason]
    message = (f"{position['side']} {symbol}: {entry:.4g} → {exit_price:.4g} ({_pct(move)})\n"
               f"Net P&L {result['net_pnl']:+,.2f}" + (f" · account {account['name']}" if account else ""))
    send(f"exit:{position['id']}", "exit", f"{'✅' if (result['net_pnl'] or 0) >= 0 else '⛔'} {label}: {symbol}",
         message, priority=4 if reason == "stop" else 3, tags=["moneybag"], click=asset_link(position["instrument_id"]))


# ── Price moves ──────────────────────────────────────────────────────────────

_sigma: dict[str, tuple[str, float | None]] = {}


def daily_sigma(instrument_id: str) -> float | None:
    """Standard deviation of the asset's daily % change over its last 60 stored sessions."""
    today = db.today()
    cached = _sigma.get(instrument_id)
    if cached and cached[0] == today:
        return cached[1]
    closes = [r["close"] for r in reversed(db.rows(
        "SELECT close FROM bars WHERE instrument_id=? AND close>0 ORDER BY date DESC LIMIT 61", (instrument_id,)))]
    changes = [(b / a - 1) * 100 for a, b in zip(closes, closes[1:]) if a]
    value = None
    if len(changes) >= 20:
        mean = sum(changes) / len(changes)
        value = math.sqrt(sum((c - mean) ** 2 for c in changes) / (len(changes) - 1)) or None
    _sigma[instrument_id] = (today, value)
    return value


def check_moves() -> dict:
    """Abnormal moves today on watched assets and market gauges. Run every few minutes."""
    threshold = config.get_float("notify_move_sigma")
    if not enabled() or threshold <= 0:
        return {"checked": 0, "sent": 0}
    from .ingest import prices

    watched = watched_ids()
    ids = sorted(watched | set(CORE))
    quotes = prices.quotes(ids)
    fresh_after = datetime.now(timezone.utc) - timedelta(hours=18)
    sent = 0
    # Biggest surprise first, so the most important push lands on top.
    ordered = sorted(quotes.items(), key=lambda kv: -abs((kv[1].get("change_pct") or 0)
                                                         / (daily_sigma(kv[0]) or float("inf"))))
    for instrument_id, quote in ordered:
        change = quote.get("change_pct")
        if change is None or not quote.get("as_of"):
            continue
        try:
            as_of = datetime.fromisoformat(quote["as_of"])
        except ValueError:
            continue
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        if as_of < fresh_after:
            continue
        sigma = daily_sigma(instrument_id)
        if not sigma or abs(change) < 1.0:
            continue
        z = change / sigma
        if abs(z) < threshold:
            continue
        # Once per day and direction, again if the move doubles past the threshold.
        step = int(abs(z) // threshold)
        key = f"move:{instrument_id}:{as_of.date()}:{'up' if change > 0 else 'down'}:{step}"
        symbol = _symbol(instrument_id)
        mine = instrument_id in watched
        message = (f"{symbol} {change:+.2f}% today at {quote['price']:.4g}, a {abs(z):.1f}σ move "
                   f"(typical day ±{sigma:.1f}%).")
        if not quote.get("market_open"):
            message += " Market closed: last trade."
        link = asset_link(instrument_id)
        if send(key, "move", f"{'📈' if change > 0 else '📉'} {symbol} {change:+.1f}% ({abs(z):.1f}σ)", message,
                priority=4 if abs(z) >= threshold + 1 or mine else 3,
                tags=["chart_with_upwards_trend" if change > 0 else "chart_with_downwards_trend"], click=link):
            sent += 1
            if mine and abs(z) >= threshold + 1 and not config.get_bool("event_trader"):
                maybe_auto_analyst(f"{symbol} moved {change:+.1f}% today ({abs(z):.1f}σ). Find out why and whether "
                                   f"it is a buy, a sell or a reason to change an open position.")
    return {"checked": len(quotes), "sent": sent}


# ── Analyst on demand ────────────────────────────────────────────────────────

def maybe_auto_analyst(focus: str) -> bool:
    """Start a focused analyst run when something big happens (rate-limited)."""
    if not config.get_bool("notify_auto_analyst"):
        return False
    if time.time() - _last_auto["at"] < AUTO_ANALYST_EVERY_S:
        return False
    from . import jobs

    if not jobs.llm_ready() or not jobs.has_data():
        return False
    try:
        jobs.run_analyst_async(focus)
    except RuntimeError:  # already running
        return False
    _last_auto["at"] = time.time()
    db.log("info", "notify", f"auto analyst: {focus[:200]}")
    return True
