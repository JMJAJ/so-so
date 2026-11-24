import threading
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from nexus import config, db, notify, universe
from nexus.ingest import prices

REAL_QUOTES = prices.quotes


@pytest.fixture()
def pushes(nexus_db, monkeypatch):
    """Capture what would be posted to ntfy instead of sending it."""
    sent = []
    monkeypatch.setenv("NTFY_TOPIC", "nexus-test-topic")

    class Response:
        status_code = 200
        text = "ok"

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.append(json)
        return Response()

    monkeypatch.setattr(notify.requests, "post", fake_post)

    class Inline:  # deliver synchronously so tests can assert right away
        def __init__(self, target, **_):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(notify.threading, "Thread", Inline)
    monkeypatch.setattr(notify, "maybe_auto_analyst", lambda focus: False)
    return sent


def test_send_once_per_key(pushes):
    assert notify.send("k1", "test", "Title", "Body")
    assert not notify.send("k1", "test", "Title", "Body")
    assert len(pushes) == 1
    assert pushes[0]["topic"] == "nexus-test-topic"
    assert notify.recent()[0]["status"] == "sent"


def test_nothing_sent_without_topic(nexus_db, monkeypatch):
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    assert not notify.enabled()
    assert not notify.send("k", "test", "t", "m")


def test_abnormal_move_is_pushed_in_sigmas(pushes, synthetic, monkeypatch):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def quotes(ids):
        return {i: {"instrument_id": i, "price": 100.0, "as_of": now, "stale": False, "market_open": True,
                    "change_pct": 9.0 if i == "stock:nvda" else 0.3} for i in ids if universe.resolve(i)}

    monkeypatch.setattr(prices, "quotes", quotes)
    notify.set_watchlist(["stock:nvda", "stock:aapl"])
    result = notify.check_moves()
    assert result["sent"] == 1
    assert "NVDA +9.0%" in pushes[0]["title"]
    assert "σ" in pushes[0]["title"]
    # Same move again: no repeat.
    assert notify.check_moves()["sent"] == 0


def test_small_move_for_volatile_asset_is_quiet(pushes, synthetic, monkeypatch):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sigma = notify.daily_sigma("index:vix")
    assert sigma and sigma > 3  # synthetic VIX moves ~6% a day

    monkeypatch.setattr(prices, "quotes", lambda ids: {i: {"price": 20.0, "as_of": now, "market_open": True,
                                                          "change_pct": sigma * 1.5 if i == "index:vix" else 0.0}
                                                      for i in ids})
    assert notify.check_moves()["sent"] == 0


def test_news_alert_rules(pushes):
    notify.set_watchlist(["stock:aapl"])
    base = {"source": "Reuters", "url": "https://example.com/a", "moves": {}}
    alerts = [
        {**base, "id": "n1", "title": "Fed delivers surprise cut", "tickers": [], "kinds": ["central-bank"], "level": 3},
        {**base, "id": "n2", "title": "Apple faces probe", "tickers": ["stock:aapl"], "kinds": ["regulatory"], "level": 2},
        {**base, "id": "n3", "title": "Ford faces probe", "tickers": ["stock:f"], "kinds": ["regulatory"], "level": 2},
    ]
    notify.on_alerts(alerts)
    titles = [p["message"].splitlines()[0] for p in pushes]
    assert "Fed delivers surprise cut" in titles  # top level: always
    assert "Apple faces probe" in titles  # major and on the watchlist
    assert "Ford faces probe" not in titles  # major but not followed


def test_call_notification(pushes):
    rec = {"id": "rec_1", "instrument_id": "stock:nvda", "direction": "long", "entry_price": 100.0,
           "horizon_days": 20, "stop": 95.0, "target": 112.0, "probability": 0.58, "expected_return": 0.021,
           "thesis": "Earnings drift after a beat with reliable evidence."}
    notify.on_call(rec)
    assert "BUY NVDA" in pushes[0]["title"]
    assert "P(win) 58%" in pushes[0]["message"]
    assert "EV +2.1%" in pushes[0]["message"]


def test_watchlist_round_trip(nexus_db):
    assert notify.set_watchlist(["AAPL", "stock:aapl", "BTC", "nope"]) == ["stock:aapl", "crypto:btc"]
    assert notify.watchlist() == ["stock:aapl", "crypto:btc"]
    assert config.get("watchlist") == "stock:aapl,crypto:btc"


def test_previous_close_uses_current_bars_and_falls_back_to_yahoo(nexus_db, monkeypatch):
    item = universe.require("stock:aapl")
    monday = date(2026, 11, 23)
    db.execute("INSERT INTO bars(instrument_id,date,open,high,low,close,volume) VALUES(?,?,?,?,?,?,?)",
               (item.id, "2026-11-20", 1, 1, 1, 200.0, 1))
    prices._prev_close.clear()
    asked = []
    monkeypatch.setattr(prices.yf, "download", lambda *a, **k: asked.append(a) or None)
    # Friday's stored close is the previous session for Monday: no network.
    assert prices.previous_closes([(item, monday)])[item.id] == 200.0
    assert not asked
    # Weeks behind: ask Yahoo rather than call a month of movement "today".
    prices._prev_close.clear()
    later = monday + timedelta(days=21)
    prices.previous_closes([(item, later)])
    assert asked


def test_universe_quotes_never_wait_on_yahoo(nexus_db, monkeypatch):
    """The search list asks for every instrument; it answers from stored closes at once and
    refreshes in the background, and a symbol Yahoo can't price isn't retried on every call."""
    monkeypatch.setattr(prices, "quotes", REAL_QUOTES)  # the fixture stubs it; test the real one
    monkeypatch.setattr(prices, "_attempted", {})
    monkeypatch.setattr(prices, "_quotes", {})
    item = universe.require("stock:aapl")
    db.execute("INSERT INTO bars(instrument_id,date,open,high,low,close,volume) VALUES(?,?,?,?,?,?,?)",
               (item.id, "2026-11-20", 1, 1, 1, 200.0, 1))
    started, release = threading.Event(), threading.Event()
    calls = []

    def slow_refresh(items):
        calls.append([i.id for i in items])
        started.set()
        release.wait(5)
        for i in items:
            prices._attempted[i.id] = time.time()

    monkeypatch.setattr(prices, "_refresh_quotes", slow_refresh)
    out = prices.quotes([item.id, "crypto:btc"], wait=False)
    assert out[item.id]["price"] == 200.0 and out[item.id]["stale"]
    assert started.wait(2)
    prices.quotes([item.id], wait=False)  # one background refresh at a time
    release.set()
    for _ in range(100):
        if prices._background.acquire(blocking=False):
            prices._background.release()
            break
        time.sleep(0.02)
    prices.quotes([item.id], wait=False)  # just attempted: no new download
    assert calls == [[item.id, "crypto:btc"]]
