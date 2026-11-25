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


def test_small_accounts_get_fractional_commodity_contracts(synthetic):
    gold = __import__("nexus.universe", fromlist=["x"]).require("commodity:gold")
    # A $1.2k account, gold at 3555 with a 105 stop: one 100 oz contract is ~$355k of exposure.
    small = paper.size_for(gold, 3555.0, 3450.0, 1_174.47, 0.35)
    assert 0 < small < 1
    assert paper.notional(gold, small, 3555.0) <= 1_174.47 * paper.MAX_POSITION_PCT + 1e-6
    whole = paper.size_for(gold, 3555.0, 3450.0, 50_000_000)
    assert whole == int(whole) and whole >= 1


def test_chat_can_trade_a_recorded_call(synthetic):
    from nexus.agent import tools

    rec = _call("stock:aapl", auto_trade=False)
    assert not rec["traded"]
    text, error = tools.call("trade_recommendation", {"recommendation_id": rec["id"]}, extra={"_source": "chat"})
    assert not error and "OPENED" in text
    assert recommendations.get(rec["id"])["traded"]
    again, error = tools.call("trade_recommendation", {"recommendation_id": rec["id"]}, extra={"_source": "chat"})
    assert error and "already" in again
    other = _call("stock:msft", auto_trade=False)
    denied, error = tools.call("trade_recommendation", {"recommendation_id": other["id"]}, extra={"_source": "analyst"})
    assert error and "Only the user" in denied


def _call(instrument_id: str, auto_trade: bool) -> dict:
    price = db.one("SELECT close FROM bars WHERE instrument_id=? ORDER BY date DESC LIMIT 1", (instrument_id,))["close"]
    return recommendations.create(
        {"instrument_id": instrument_id, "direction": "long", "horizon_days": 20, "stop": price * 0.94,
         "target": price * 1.1, "probability": 0.55, "confidence": "low",
         "thesis": "Synthetic thesis long enough to be valid.", "evidence": [{"type": "analogs", "summary": "x"}]},
        source="test", auto_trade=auto_trade)


def test_untraded_call_is_replaced_not_blocking(synthetic):
    old = _call("stock:aapl", auto_trade=False)
    assert old["traded"] is False
    new = _call("stock:aapl", auto_trade=False)
    assert recommendations.get(old["id"])["exit_reason"] == "superseded" and new["status"] == "open"
    traded = recommendations.trade(new["id"])
    assert traded["traded"] is True
    with pytest.raises(ValueError, match="Already holding AAPL in this account"):
        _call("stock:aapl", auto_trade=False)


def test_reset_starts_a_clean_account(synthetic):
    _call("stock:msft", auto_trade=True)
    _call("stock:jpm", auto_trade=False)
    assert paper.portfolio()["open_count"] + paper.portfolio()["pending_count"] == 1
    result = paper.reset_account(983)
    assert result["closed_positions"] == 1
    state = paper.portfolio()
    assert state["equity"] == pytest.approx(983) and state["trade_count"] == 0 and not state["positions"]
    assert len(recommendations.list_recs("open")) == 2  # shared AI calls are research, not the account's
    assert len(paper.equity_curve()) == 1



def test_accounts_are_isolated(synthetic):
    from nexus import accounts

    _call("stock:msft", auto_trade=True)  # Main
    second = accounts.create("Small bets", "2,500", gate="any")
    with accounts.use(second["id"]):
        state = paper.portfolio()
        assert state["starting_equity"] == 2500 and state["equity"] == 2500 and not state["positions"]
        rec = recommendations.list_recs("open")[0]
        assert rec["traded"] is False  # traded in Main, not here
        recommendations.trade(rec["id"])  # same call, second account
        assert paper.portfolio()["open_count"] + paper.portfolio()["pending_count"] == 1
        paper.reset_account()
        assert not paper.portfolio()["positions"]
    assert paper.portfolio()["open_count"] + paper.portfolio()["pending_count"] == 1  # Main untouched
    with pytest.raises(ValueError, match="can't be deleted"):
        accounts.delete("main")
    accounts.delete(second["id"])
    assert [a["id"] for a in accounts.all_accounts()] == ["main"]


def test_old_equity_snapshots_migrate_to_main(nexus_db):
    with db.session() as conn:
        conn.executescript("""
            DROP TABLE equity_snapshots;
            CREATE TABLE equity_snapshots (date TEXT PRIMARY KEY, equity REAL NOT NULL, cash REAL NOT NULL,
                                           exposure REAL NOT NULL, spy_close REAL) WITHOUT ROWID;
            INSERT INTO equity_snapshots VALUES ('2026-10-20', 100000, 50000, 50000, 700);
        """)
    db.init_db()
    rows = db.rows("SELECT account_id, date, equity FROM equity_snapshots")
    assert rows == [{"account_id": "main", "date": "2026-10-20", "equity": 100000}]
