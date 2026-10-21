"""Paper broker, recommendation lifecycle and the track record."""

from datetime import date, timedelta

import pytest

from nexus import config, db, paper, recommendations


def _add_bar(instrument_id: str, day: str, low: float, high: float, close: float, open_: float | None = None) -> None:
    db.execute(
        "INSERT OR REPLACE INTO bars(instrument_id,date,open,high,low,close,volume) VALUES(?,?,?,?,?,?,?)",
        (instrument_id, day, close if open_ is None else open_, high, low, close, 1e6),
    )


def _last_close(instrument_id: str) -> float:
    return db.one("SELECT close FROM bars WHERE instrument_id=? ORDER BY date DESC LIMIT 1", (instrument_id,))["close"]


def test_position_sizing_risks_one_percent_and_stop_exits(synthetic):
    price = _last_close("stock:aapl")
    stop = price * 0.95
    position = paper.open_position("stock:aapl", "long", stop=stop, target=price * 1.1, expires_at=None)
    assert position["status"] == "open"
    risk = (position["entry_price"] - stop) * position["quantity"]
    assert risk == pytest.approx(1000, rel=0.05)  # 1% of 100k

    _add_bar("stock:aapl", (date.today() + timedelta(days=1)).isoformat(), low=stop * 0.99, high=price, close=stop, open_=price)
    assert paper.monitor()["closed"] == 1
    trade = db.one("SELECT * FROM trades")
    assert trade["exit_reason"] == "stop"
    assert trade["net_pnl"] == pytest.approx(-1000, rel=0.1)
    assert paper.portfolio()["equity"] == pytest.approx(99000, rel=0.002)


def test_duplicate_and_limits_are_enforced(synthetic):
    price = _last_close("etf:spy")
    paper.open_position("etf:spy", "long", stop=price * 0.95, target=None, expires_at=None)
    with pytest.raises(ValueError):
        paper.open_position("etf:spy", "long", stop=price * 0.95, target=None, expires_at=None)
    with pytest.raises(ValueError):
        paper.open_position("etf:gld", "long", stop=_last_close("etf:gld") * 1.05, target=None, expires_at=None)
    with pytest.raises(ValueError):
        paper.open_position("index:vix", "long", stop=1, target=None, expires_at=None)


def _rec_payload(instrument_id: str, price: float, **overrides) -> dict:
    payload = {
        "instrument_id": instrument_id, "direction": "long", "horizon_days": 20,
        "stop": price * 0.95, "target": price * 1.08, "probability": 0.6, "confidence": "medium",
        "thesis": "Planted thesis that is long enough to pass validation.",
        "evidence": [{"type": "event_study", "summary": "test evidence", "n": 12, "stat": 2.4}],
    }
    payload.update(overrides)
    return payload


def test_recommendation_validation(synthetic):
    price = _last_close("stock:msft")
    with pytest.raises(ValueError):
        recommendations.create(_rec_payload("stock:msft", price, stop=price * 1.01), source="test")
    with pytest.raises(ValueError):
        recommendations.create(_rec_payload("stock:msft", price, evidence=[]), source="test")
    rec = recommendations.create(_rec_payload("stock:msft", price), source="test")
    assert rec["status"] == "open" and rec["position_id"]
    with pytest.raises(ValueError):
        recommendations.create(_rec_payload("stock:msft", price), source="test")  # one open call per asset


def test_recommendation_scored_at_target_and_track_record(synthetic):
    config.set_many({"autopilot": "false"})
    price = _last_close("stock:jpm")
    rec = recommendations.create(_rec_payload("stock:jpm", price), source="test")
    assert rec["position_id"] is None
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    _add_bar("stock:jpm", tomorrow, low=price, high=price * 1.09, close=price * 1.085, open_=price)
    _add_bar("etf:spy", tomorrow, low=1, high=1e9, close=_last_close("etf:spy") * 1.01)
    assert recommendations.score_open()["closed"] == 1
    closed = recommendations.get(rec["id"])
    assert closed["exit_reason"] == "target"
    assert closed["realized_return"] == pytest.approx(0.08, abs=0.002)
    assert closed["excess_return"] < closed["realized_return"]
    record = recommendations.track_record()
    assert record["overall"]["n"] == 1 and record["overall"]["hit_rate"] == 1.0
    assert "event_study" in record["by_evidence"]
    assert "hit rate 100%" in recommendations.lessons()


def test_cancel_closes_position(synthetic):
    price = _last_close("stock:xom")
    rec = recommendations.create(_rec_payload("stock:xom", price), source="test")
    recommendations.cancel(rec["id"])
    assert recommendations.get(rec["id"])["status"] == "cancelled"
    assert db.one("SELECT COUNT(*) c FROM positions")["c"] == 0


def test_state_changes_publish_live_events(synthetic):
    from nexus import live

    start = live.current_seq()
    price = db.one("SELECT close FROM bars WHERE instrument_id='etf:spy' ORDER BY date DESC LIMIT 1")["close"]
    position = paper.open_position("etf:spy", "long", stop=price * 0.95, target=None, expires_at=None)
    paper.close_position(position["id"], reason="manual")
    topics = [e["topic"] for e in live.wait(start, timeout=0)]
    assert topics.count("portfolio") >= 2 and "logs" in topics
    assert live.wait(live.current_seq(), timeout=0.05) == []


def test_small_accounts_get_fractional_shares(synthetic):
    config.set_many({"starting_equity": "2000"})
    item = __import__("nexus.universe", fromlist=["x"]).require("stock:msft")
    whole = paper.size_for(item, 300.0, 285.0, 100_000)
    small = paper.size_for(item, 3000.0, 2850.0, 2_000)
    assert whole == int(whole) and whole > 1
    assert 0 < small < 1  # one share would cost more than the account's position cap
    assert paper.portfolio()["starting_equity"] == 2000
