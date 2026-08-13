import sqlite3

import db
import execution
import prices
from instruments import get_instrument


def quote(instrument_id: str, price: float = 100.0) -> dict:
    return {
        "instrument_id": instrument_id,
        "symbol": instrument_id.split(":")[-1].upper(),
        "price": price,
        "change": 1.0,
        "change_pct": 1.0,
        "as_of": "2026-08-13T12:00:00+00:00",
        "source": "test",
        "delayed": False,
        "stale": False,
        "market_status": "open",
    }


def setup_account(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "nexus.db"))
    db.init_db()
    monkeypatch.setattr(prices, "fetch_quote", lambda instrument_id: quote(instrument_id))
    monkeypatch.setattr(
        prices,
        "fetch_quotes",
        lambda instrument_ids: {instrument_id: quote(instrument_id) for instrument_id in instrument_ids},
    )


def test_preview_enforces_stop_geometry_and_research_gate(tmp_path, monkeypatch):
    setup_account(tmp_path, monkeypatch)
    valid = execution.preview_order(
        {"instrument_id": "stock:aapl", "side": "long", "quantity": 10, "stop_loss": 95, "take_profit": 110}
    )
    assert valid["allowed"] is True
    assert valid["risk_amount"] > 0

    invalid = execution.preview_order(
        {"instrument_id": "stock:aapl", "side": "long", "quantity": 10, "stop_loss": 105, "take_profit": 110}
    )
    assert invalid["allowed"] is False
    assert "invalid_stop" in {item["code"] for item in invalid["errors"]}

    derivative = execution.preview_order(
        {"instrument_id": "future:es", "side": "long", "quantity": 1, "stop_loss": 95, "take_profit": 110}
    )
    assert "research_only" in {item["code"] for item in derivative["errors"]}


def test_order_is_idempotent_and_close_is_audited(tmp_path, monkeypatch):
    setup_account(tmp_path, monkeypatch)
    payload = {
        "instrument_id": "stock:aapl",
        "side": "long",
        "quantity": 10,
        "stop_loss": 95,
        "take_profit": 110,
        "idempotency_key": "stable-request",
    }
    first = execution.execute_order(payload)
    second = execution.execute_order(payload)
    assert first["status"] == "filled"
    assert second["id"] == first["id"]
    assert len(execution.portfolio_snapshot()["positions"]) == 1

    closed = execution.close_position(first["position_id"])
    assert closed["trade_id"].startswith("t")
    assert execution.portfolio_snapshot()["positions"] == []
    conn = sqlite3.connect(db.DB_PATH)
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1
    conn.close()


def test_guarded_source_requires_stop_and_kill_switch_blocks_entry(tmp_path, monkeypatch):
    setup_account(tmp_path, monkeypatch)
    no_stop = execution.preview_order(
        {"instrument_id": "crypto:btc-usd", "side": "long", "quantity": 0.01}, source="autopilot"
    )
    assert "stop_required" in {item["code"] for item in no_stop["errors"]}

    conn = db.get_db()
    conn.execute("UPDATE portfolio_config SET value='true' WHERE key='kill_switch'")
    conn.commit()
    conn.close()
    blocked = execution.preview_order(
        {"instrument_id": "stock:aapl", "side": "long", "quantity": 1, "stop_loss": 95, "take_profit": 110}
    )
    assert "kill_switch" in {item["code"] for item in blocked["errors"]}


def test_protective_exit_remains_available(tmp_path, monkeypatch):
    setup_account(tmp_path, monkeypatch)
    order = execution.execute_order(
        {"instrument_id": "stock:aapl", "side": "long", "quantity": 1, "stop_loss": 95, "take_profit": 110}
    )
    monkeypatch.setattr(prices, "fetch_quote", lambda instrument_id: quote(instrument_id, 94.0))
    exits = execution.check_protective_exits()
    assert len(exits) == 1
    assert exits[0]["reason"] == "stop_loss"
    assert execution.portfolio_snapshot()["positions"] == []


def test_forex_conversion_multiplier_and_visible_friction(tmp_path, monkeypatch):
    setup_account(tmp_path, monkeypatch)
    usd_jpy = get_instrument("forex:usdjpy")
    es = get_instrument("future:es")
    assert usd_jpy is not None and es is not None
    assert round(execution.calculate_pnl(usd_jpy, "long", 10_000, 100, 101), 4) == 99.0099
    assert execution.calculate_pnl(es, "short", 2, 5_000, 4_999) == 100

    crypto = execution.preview_order(
        {
            "instrument_id": "crypto:btc-usd",
            "side": "long",
            "quantity": 1,
            "stop_loss": 95,
            "take_profit": 110,
        }
    )
    assert crypto["slippage_bps"] == 10
    assert crypto["fee"] > 0
    assert crypto["estimated_exit_fee"] > 0
    assert crypto["risk_amount"] > abs(crypto["estimated_fill"] - 95)


def test_all_fixed_risk_presets_are_available():
    assert execution.RISK_PROFILES == {
        "conservative": {"risk_per_trade": 0.005, "daily_loss": 0.02, "max_exposure": 0.5, "max_positions": 6},
        "balanced": {"risk_per_trade": 0.01, "daily_loss": 0.03, "max_exposure": 0.8, "max_positions": 10},
        "aggressive": {"risk_per_trade": 0.02, "daily_loss": 0.05, "max_exposure": 1.5, "max_positions": 12},
    }
