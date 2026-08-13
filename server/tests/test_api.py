import sqlite3

from fastapi.testclient import TestClient

import crypto_utils
import db
import main
import prices


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


def api_client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setattr(prices, "fetch_quote", lambda instrument_id: quote(instrument_id))
    monkeypatch.setattr(
        prices,
        "fetch_quotes",
        lambda instrument_ids: {instrument_id: quote(instrument_id) for instrument_id in instrument_ids},
    )
    monkeypatch.setattr(
        prices,
        "provider_health",
        lambda: {"provider": "test", "ok": True, "delayed": False, "stale_count": 0},
    )
    return TestClient(main.app)


def test_preview_open_protect_and_close_flow(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as client:
        payload = {
            "instrument_id": "stock:aapl",
            "side": "long",
            "quantity": 2,
            "stop_loss": 95,
            "take_profit": 110,
            "idempotency_key": "api-order-1",
        }
        preview = client.post("/api/orders/preview", json=payload)
        assert preview.status_code == 200
        assert preview.json()["allowed"] is True

        opened = client.post("/api/orders", json=payload)
        assert opened.status_code == 200
        order = opened.json()
        repeated = client.post("/api/orders", json=payload)
        assert repeated.json()["id"] == order["id"]

        protected = client.patch(
            f"/api/positions/{order['position_id']}/protection",
            json={"stop_loss": 96, "take_profit": 112},
        )
        assert protected.status_code == 200
        assert protected.json()["stop_loss"] == 96

        closed = client.post(f"/api/positions/{order['position_id']}/close")
        assert closed.status_code == 200
        assert client.get("/api/positions").json() == []


def test_proposal_approval_kill_switch_and_structured_failure(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as client:
        proposal = client.post(
            "/api/proposals",
            json={
                "instrument_id": "stock:amd",
                "side": "long",
                "quantity": 1,
                "stop_loss": 95,
                "take_profit": 110,
                "confidence": 0.8,
                "rationale": "Deterministic integration test",
            },
        ).json()
        approved = client.post(f"/api/proposals/{proposal['id']}/approve")
        assert approved.status_code == 200
        assert approved.json()["proposal"]["status"] == "executed"

        killed = client.post("/api/agent/kill-switch", json={"enabled": True})
        assert killed.status_code == 200
        assert killed.json()["kill_switch"] is True
        blocked = client.post(
            "/api/orders",
            json={
                "instrument_id": "stock:aapl",
                "side": "long",
                "quantity": 1,
                "stop_loss": 95,
                "take_profit": 110,
            },
        )
        assert blocked.status_code == 422
        detail = blocked.json()["detail"]
        assert detail["code"] == "kill_switch"
        assert detail["message"]


def test_blank_llm_key_preserves_encrypted_value(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as client:
        first = client.put(
            "/api/llm/config",
            json={"provider": "openai", "model": "gpt-5-mini", "api_key": "sk-test-secret"},
        )
        assert first.status_code == 200
        conn = sqlite3.connect(db.DB_PATH)
        encrypted_before = conn.execute("SELECT api_key FROM llm_config WHERE id=1").fetchone()[0]
        conn.close()
        assert crypto_utils.decrypt(encrypted_before) == "sk-test-secret"

        second = client.put(
            "/api/llm/config",
            json={"provider": "openai", "model": "gpt-5-mini", "api_key": ""},
        )
        assert second.status_code == 200
        conn = sqlite3.connect(db.DB_PATH)
        encrypted_after = conn.execute("SELECT api_key FROM llm_config WHERE id=1").fetchone()[0]
        conn.close()
        assert encrypted_after == encrypted_before
