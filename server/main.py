"""NEXUS local paper-trading API."""

from __future__ import annotations

import json
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import requests
import yfinance as yf
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

import crypto_utils
import db
import execution
import llm as llm_module
import prices
import proposals
from agent import agent
from instruments import INSTRUMENTS, public_catalog, resolve_instrument


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error(status: int, code: str, message: str, details: object | None = None) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message, "details": details})


_monitor_stop = threading.Event()


def _protective_monitor() -> None:
    while not _monitor_stop.wait(10):
        try:
            execution.check_protective_exits()
        except Exception:
            continue


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    agent.reload_provider()
    agent.stop()
    _monitor_stop.clear()
    monitor = threading.Thread(target=_protective_monitor, daemon=True, name="nexus-protection-monitor")
    monitor.start()
    yield
    agent.stop()
    _monitor_stop.set()


app = FastAPI(title="NEXUS Paper Trading API", version="2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


class OrderRequest(BaseModel):
    instrument_id: str
    side: str
    quantity: float
    stop_loss: float | None = None
    take_profit: float | None = None
    confidence: float = Field(0.75, ge=0, le=1)
    allow_unprotected: bool = False
    idempotency_key: str | None = None

    @field_validator("quantity")
    @classmethod
    def positive_quantity(cls, value: float) -> float:
        if value <= 0 or value > 1_000_000_000:
            raise ValueError("Quantity must be positive and within the paper-account limit")
        return value


class LegacyPositionRequest(BaseModel):
    pair: str
    asset_class: str
    side: str
    size: float
    confidence: float = 0.7
    stop_loss: float | None = None
    take_profit: float | None = None
    allow_unprotected: bool = True


class ProtectionUpdate(BaseModel):
    stop_loss: float | None = None
    take_profit: float | None = None


class ProposalRequest(BaseModel):
    instrument_id: str
    side: str
    quantity: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    confidence: float = Field(0.5, ge=0, le=1)
    rationale: str = ""


class RejectRequest(BaseModel):
    reason: str = "Rejected by operator"


class AgentConfigUpdate(BaseModel):
    mode: str | None = None
    risk_profile: str | None = None
    allowed_asset_classes: list[str] | None = None
    interval_seconds: int | None = None


class KillSwitchRequest(BaseModel):
    enabled: bool


class ConfigUpdate(BaseModel):
    starting_equity: float | None = None
    display_currency: str | None = None
    risk_profile: str | None = None
    allowed_asset_classes: str | None = None


class LLMConfigUpdate(BaseModel):
    provider: str
    model: str
    api_key: str | None = None
    base_url: str | None = None
    num_ctx: int = 8192


class NewAnnotation(BaseModel):
    symbol: str
    type: str
    data: dict
    color: str | None = None


class NewTradeIdea(BaseModel):
    symbol: str
    asset_class: str
    side: str
    entry_price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    confidence: float | None = None
    reasoning: str | None = None


def _read_config() -> dict:
    conn = db.get_db()
    values = {row["key"]: row["value"] for row in conn.execute("SELECT key,value FROM portfolio_config")}
    conn.close()
    profile = values.get("risk_profile", "balanced")
    if profile == "moderate":
        profile = "balanced"
    return {
        "starting_equity": float(values.get("starting_equity", "100000")),
        "display_currency": values.get("display_currency", "USD"),
        "fx_rate": 1.0,
        "risk_profile": profile,
        "risk_limits": execution.RISK_PROFILES.get(profile, execution.RISK_PROFILES["balanced"]),
        "allowed_asset_classes": values.get("allowed_asset_classes", "forex,stock,crypto,cfd,futures"),
        "agent_mode": values.get("agent_mode", "advisory"),
        "kill_switch": values.get("kill_switch", "false") == "true",
        "last_backup_path": values.get("last_backup_path"),
    }


def _system_status(quote_health: dict | None = None) -> dict:
    market = quote_health or prices.provider_health()
    status = agent.status()
    configured = bool(status.get("provider") and status.get("model"))
    return {
        "backend": {"ok": True, "version": "2.0"},
        "database": {"ok": True, "path": db.DB_PATH, "backup_path": db.last_backup_path()},
        "market_data": market,
        "llm": {"configured": configured, "provider": status.get("provider"), "model": status.get("model")},
        "autopilot_ready": bool(market.get("ok") and configured and not status.get("kill_switch")),
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "time": _now(), "mode": "paper"}


@app.get("/api/system/status")
def system_status():
    return _system_status()


@app.get("/api/bootstrap")
def bootstrap():
    execution.check_protective_exits()
    portfolio = execution.portfolio_snapshot(persist=True)
    catalog = public_catalog()
    quote_map = prices.fetch_quotes([item["id"] for item in catalog])
    conn = db.get_db()
    trades = [dict(row) for row in conn.execute("SELECT * FROM trades ORDER BY closed_at DESC LIMIT 100").fetchall()]
    orders = [dict(row) for row in conn.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 100").fetchall()]
    logs = [dict(row) for row in conn.execute("SELECT * FROM logs ORDER BY created_at DESC LIMIT 100").fetchall()]
    ideas = [dict(row) for row in conn.execute("SELECT * FROM trade_ideas ORDER BY created_at DESC LIMIT 100").fetchall()]
    runs = [dict(row) for row in conn.execute("SELECT * FROM agent_runs ORDER BY started_at DESC LIMIT 30").fetchall()]
    conn.close()
    market_health = {
        "provider": "yfinance", "ok": any(q["price"] is not None for q in quote_map.values()),
        "delayed": True, "stale_count": sum(1 for q in quote_map.values() if q["stale"]),
    }
    return {
        "as_of": _now(), "portfolio": portfolio, "positions": portfolio["positions"],
        "trades": trades, "orders": orders, "proposals": proposals.list_proposals(),
        "trade_ideas": ideas, "logs": logs, "agent_runs": runs,
        "agent": agent.status(), "instruments": catalog, "quotes": quote_map,
        "config": _read_config(), "system": _system_status(market_health),
    }


@app.get("/api/instruments")
def instruments():
    return public_catalog()


@app.get("/api/quotes")
def quotes(instrument_ids: str = ""):
    ids = [item.strip() for item in instrument_ids.split(",") if item.strip()]
    if not ids:
        ids = [item.id for item in INSTRUMENTS]
    return prices.fetch_quotes(ids)


@app.get("/api/watchlist")
def legacy_watchlist():
    quote_map = prices.fetch_quotes([item.id for item in INSTRUMENTS])
    return [
        {
            "instrument_id": item.id, "pair": item.symbol, "asset_class": item.asset_class,
            "price": quote_map[item.id]["price"], "change_pct": quote_map[item.id]["change_pct"],
            "stale": quote_map[item.id]["stale"], "eligibility": item.eligibility,
        }
        for item in INSTRUMENTS
    ]


@app.get("/api/prices")
def legacy_prices(symbols: str = ""):
    return prices.fetch_prices([item.strip() for item in symbols.split(",") if item.strip()])


@app.post("/api/orders/preview")
def order_preview(request: OrderRequest):
    return execution.preview_order(request.model_dump(), source="manual")


@app.post("/api/orders")
def create_order(request: OrderRequest):
    result = execution.execute_order(request.model_dump(), source="manual")
    if result["status"] == "rejected":
        raise _error(422, result["rejection_code"], result["rejection_reason"], result.get("preview"))
    return result


@app.get("/api/orders")
def list_orders(limit: int = Query(100, ge=1, le=500)):
    conn = db.get_db()
    rows = conn.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.get("/api/positions")
def list_positions():
    return execution.portfolio_snapshot()["positions"]


@app.post("/api/positions")
def legacy_open_position(request: LegacyPositionRequest):
    instrument = resolve_instrument(request.pair, request.asset_class)
    if not instrument:
        raise _error(400, "unknown_instrument", "Instrument is not in the curated catalog")
    result = execution.execute_order(
        {
            "instrument_id": instrument.id, "side": request.side, "quantity": request.size,
            "confidence": request.confidence, "stop_loss": request.stop_loss,
            "take_profit": request.take_profit, "allow_unprotected": request.allow_unprotected,
            "idempotency_key": f"legacy:{uuid.uuid4().hex}",
        },
        source="legacy_api",
    )
    if result["status"] == "rejected":
        raise _error(422, result["rejection_code"], result["rejection_reason"])
    return result


@app.post("/api/positions/{position_id}/close")
def close_position(position_id: str):
    try:
        return execution.close_position(position_id)
    except KeyError:
        raise _error(404, "position_not_found", "Position not found")
    except ValueError as exc:
        raise _error(409, str(exc), "Position cannot be closed with the current quote")


@app.delete("/api/positions/{position_id}")
def legacy_close_position(position_id: str):
    return close_position(position_id)


@app.patch("/api/positions/{position_id}/protection")
def update_position_protection(position_id: str, request: ProtectionUpdate):
    try:
        return execution.update_protection(position_id, request.stop_loss, request.take_profit)
    except KeyError:
        raise _error(404, "position_not_found", "Position not found")
    except ValueError as exc:
        raise _error(422, str(exc), "Protective levels are invalid for the current price")


@app.get("/api/portfolio")
def portfolio():
    return execution.portfolio_snapshot()


@app.get("/api/trades")
def trades():
    conn = db.get_db()
    rows = conn.execute("SELECT * FROM trades ORDER BY closed_at DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.get("/api/logs")
def logs(limit: int = Query(50, ge=1, le=500)):
    conn = db.get_db()
    rows = conn.execute("SELECT * FROM logs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.delete("/api/logs")
def clear_logs():
    conn = db.get_db()
    conn.execute("DELETE FROM logs")
    conn.commit()
    conn.close()
    return {"status": "cleared"}


@app.get("/api/proposals")
def list_proposals(status: str | None = None):
    return proposals.list_proposals(status)


@app.post("/api/proposals")
def create_proposal(request: ProposalRequest):
    try:
        return proposals.create_proposal(request.model_dump(), source="manual_signal", auto_execute=False)
    except ValueError as exc:
        raise _error(422, str(exc), "Proposal is invalid")


@app.post("/api/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str):
    try:
        result = proposals.approve_proposal(proposal_id)
        if result["order"]["status"] == "rejected":
            raise _error(422, result["order"]["rejection_code"], result["order"]["rejection_reason"], result)
        return result
    except KeyError:
        raise _error(404, "proposal_not_found", "Proposal not found")
    except ValueError as exc:
        raise _error(409, str(exc), "Proposal is no longer pending")


@app.post("/api/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, request: RejectRequest):
    try:
        return proposals.reject_proposal(proposal_id, request.reason)
    except KeyError:
        raise _error(404, "proposal_not_found", "Proposal not found")
    except ValueError as exc:
        raise _error(409, str(exc), "Proposal is no longer pending")


@app.get("/api/agent/status")
def agent_status():
    return agent.status()


@app.post("/api/agent/start")
def agent_start(interval: int = 120):
    if not agent.start(interval):
        raise _error(409, "agent_not_started", "Agent is already running or the kill switch is active")
    return agent.status()


@app.post("/api/agent/stop")
def agent_stop():
    agent.stop()
    return agent.status()


@app.post("/api/agent/trigger")
def agent_trigger():
    if not agent.trigger():
        raise _error(409, "cycle_blocked", "A cycle is already active or the kill switch is on")
    return {"status": "triggered"}


@app.put("/api/agent/config")
def update_agent_config(request: AgentConfigUpdate):
    if request.mode is not None and request.mode not in ("advisory", "guarded_autopilot"):
        raise _error(422, "invalid_mode", "Mode must be advisory or guarded_autopilot")
    profile = "balanced" if request.risk_profile == "moderate" else request.risk_profile
    if profile is not None and profile not in execution.RISK_PROFILES:
        raise _error(422, "invalid_profile", "Unknown risk profile")
    valid_classes = {"forex", "stock", "crypto", "cfd", "futures"}
    if request.allowed_asset_classes is not None and not set(request.allowed_asset_classes).issubset(valid_classes):
        raise _error(422, "invalid_asset_class", "Unknown asset class")
    conn = db.get_db()
    updates = {
        "agent_mode": request.mode,
        "risk_profile": profile,
        "allowed_asset_classes": ",".join(request.allowed_asset_classes) if request.allowed_asset_classes else None,
    }
    for key, value in updates.items():
        if value is not None:
            conn.execute(
                "INSERT INTO portfolio_config(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
    conn.commit()
    conn.close()
    if request.interval_seconds is not None:
        agent.interval_seconds = max(30, min(request.interval_seconds, 3600))
    agent.reload_config()
    return {"agent": agent.status(), "config": _read_config()}


@app.post("/api/agent/kill-switch")
def kill_switch(request: KillSwitchRequest):
    conn = db.get_db()
    conn.execute(
        "INSERT INTO portfolio_config(key,value) VALUES('kill_switch',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        ("true" if request.enabled else "false",),
    )
    conn.commit()
    conn.close()
    if request.enabled:
        agent.stop()
    agent.reload_config()
    return agent.status()


@app.get("/api/config")
def get_config():
    return _read_config()


@app.put("/api/config")
def update_config(request: ConfigUpdate):
    conn = db.get_db()
    if request.starting_equity is not None:
        if request.starting_equity <= 0:
            conn.close()
            raise _error(422, "invalid_equity", "Starting equity must be positive")
        conn.execute("INSERT INTO portfolio_config VALUES('starting_equity',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(request.starting_equity),))
    if request.display_currency is not None:
        if request.display_currency not in ("USD", "CZK"):
            conn.close()
            raise _error(422, "invalid_currency", "Supported currencies are USD and CZK")
        conn.execute("INSERT INTO portfolio_config VALUES('display_currency',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (request.display_currency,))
    if request.risk_profile is not None:
        profile = "balanced" if request.risk_profile == "moderate" else request.risk_profile
        if profile not in execution.RISK_PROFILES:
            conn.close()
            raise _error(422, "invalid_profile", "Unknown risk profile")
        conn.execute("INSERT INTO portfolio_config VALUES('risk_profile',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (profile,))
    if request.allowed_asset_classes is not None:
        valid = {"forex", "stock", "crypto", "cfd", "futures"}
        classes = [item for item in request.allowed_asset_classes.split(",") if item in valid]
        if not classes:
            conn.close()
            raise _error(422, "invalid_asset_class", "Select at least one valid asset class")
        conn.execute("INSERT INTO portfolio_config VALUES('allowed_asset_classes',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (",".join(classes),))
    conn.commit()
    conn.close()
    agent.reload_config()
    return _read_config()


@app.get("/api/llm/config")
def get_llm_config():
    conn = db.get_db()
    row = conn.execute("SELECT * FROM llm_config WHERE id=1").fetchone()
    conn.close()
    if not row:
        return {"provider": "ollama", "model": "minimax-m3:cloud", "api_key": "", "base_url": "", "num_ctx": 8192}
    result = dict(row)
    if result["api_key"]:
        key = crypto_utils.decrypt(result["api_key"])
        result["api_key"] = f"{key[:4]}••••{key[-4:]}" if len(key) >= 8 else "••••••••"
    return result


@app.put("/api/llm/config")
def update_llm_config(request: LLMConfigUpdate):
    if request.provider not in llm_module.PROVIDERS:
        raise _error(422, "unknown_provider", "Unknown LLM provider")
    conn = db.get_db()
    current = conn.execute("SELECT * FROM llm_config WHERE id=1").fetchone()
    encrypted_key = current["api_key"] if current else ""
    if request.api_key and "•" not in request.api_key:
        encrypted_key = crypto_utils.encrypt(request.api_key)
    base_url = request.base_url if request.base_url is not None else (current["base_url"] if current else "")
    conn.execute(
        """INSERT INTO llm_config(id,provider,model,api_key,base_url,num_ctx) VALUES(1,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET provider=excluded.provider,model=excluded.model,api_key=excluded.api_key,
           base_url=excluded.base_url,num_ctx=excluded.num_ctx""",
        (request.provider, request.model, encrypted_key, base_url or "", request.num_ctx),
    )
    conn.commit()
    conn.close()
    agent.reload_provider()
    return {"status": "updated", "provider": request.provider, "model": request.model}


@app.get("/api/llm/providers")
def providers_list():
    return {key: {"name": value["name"], "needs_key": value["needs_key"], "models": value["models"]} for key, value in llm_module.PROVIDERS.items()}


@app.get("/api/llm/lmstudio/models")
def lmstudio_models():
    try:
        response = requests.get("http://localhost:1234/api/v1/models", timeout=2)
        response.raise_for_status()
        data = response.json()
        rows = data.get("models", data.get("data", []))
        return {"models": [item.get("key") or item.get("id") for item in rows if item.get("key") or item.get("id")]}
    except Exception as exc:
        return {"models": [], "error": str(exc)}


@app.post("/api/llm/test")
def test_llm():
    result = agent.test_provider()
    if not result["ok"]:
        raise _error(503, "llm_unavailable", result.get("error", "Provider test failed"), result)
    return result


@app.get("/api/trade-ideas")
def trade_ideas(status: str | None = None):
    conn = db.get_db()
    if status:
        rows = conn.execute("SELECT * FROM trade_ideas WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM trade_ideas ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.post("/api/trade-ideas")
def create_trade_idea(request: NewTradeIdea):
    instrument = resolve_instrument(request.symbol, request.asset_class)
    idea_id = f"idea_{uuid.uuid4().hex[:8]}"
    review = "valid"
    if request.stop_loss is not None and request.take_profit is not None:
        valid = (request.side == "long" and request.stop_loss < request.entry_price < request.take_profit) or (
            request.side == "short" and request.take_profit < request.entry_price < request.stop_loss
        )
        review = "valid" if valid else "invalid"
    conn = db.get_db()
    conn.execute(
        """INSERT INTO trade_ideas(id,symbol,asset_class,side,entry_price,stop_loss,take_profit,confidence,reasoning,
           status,created_at,instrument_id,review_state) VALUES(?,?,?,?,?,?,?,?,?,'active',?,?,?)""",
        (idea_id, request.symbol, request.asset_class, request.side, request.entry_price, request.stop_loss,
         request.take_profit, request.confidence, request.reasoning, _now(), instrument.id if instrument else None, review),
    )
    conn.commit()
    conn.close()
    return {"id": idea_id, "status": "created", "review_state": review}


@app.put("/api/trade-ideas/{idea_id}/close")
def close_trade_idea(idea_id: str, outcome_pnl: float | None = None):
    conn = db.get_db()
    review = "scored" if outcome_pnl is not None else "unscored"
    result = conn.execute(
        "UPDATE trade_ideas SET status='closed',closed_at=?,outcome_pnl=?,review_state=? WHERE id=? AND status='active'",
        (_now(), outcome_pnl, review, idea_id),
    )
    conn.commit()
    conn.close()
    if not result.rowcount:
        raise _error(404, "idea_not_found", "Trade idea not found or already closed")
    return {"status": "closed", "review_state": review}


@app.post("/api/trade-ideas/generate")
def generate_trade_idea(symbol: str, timeframe: str = "swing"):
    instrument = resolve_instrument(symbol)
    if not instrument:
        raise _error(404, "unknown_instrument", "Instrument is not in the curated catalog")
    quote = prices.fetch_quote(instrument.id)
    if not quote or quote["price"] is None:
        raise _error(409, "quote_unavailable", "No quote is available")
    atr = quote["price"] * (0.01 if timeframe == "scalp" else 0.02)
    side = "long" if (quote.get("change_pct") or 0) >= 0 else "short"
    stop = quote["price"] - atr if side == "long" else quote["price"] + atr
    target = quote["price"] + atr * 2 if side == "long" else quote["price"] - atr * 2
    return proposals.create_proposal(
        {
            "instrument_id": instrument.id, "side": side, "quantity": None,
            "stop_loss": stop, "take_profit": target, "confidence": 0.4,
            "rationale": "Deterministic low-confidence momentum draft; operator sizing required.",
        }, source="heuristic", auto_execute=False,
    )


@app.get("/api/trade-ideas/ohlcv")
def get_ohlcv(symbol: str, period: str = "5d", interval: str = "15m"):
    instrument = resolve_instrument(symbol)
    provider_symbol = instrument.provider_symbol if instrument else prices.pair_to_yfinance(symbol)
    periods = {"1m": "7d", "5m": "60d", "15m": "60d", "30m": "60d", "1h": "730d", "1d": "3mo"}
    if period == "auto":
        period = periods.get(interval, "5d")
    try:
        frame = yf.download(provider_symbol, period=period, interval=interval, auto_adjust=True, progress=False)
        if frame is None or frame.empty:
            raise _error(404, "history_unavailable", f"No data found for {symbol}")
        if isinstance(frame.columns, pd.MultiIndex):
            frame = frame.droplevel(1, axis=1)
        frame = frame.dropna(subset=["Close"]).sort_index()
        candles = []
        for timestamp, row in frame.iterrows():
            epoch = int(timestamp.timestamp())
            candles.append({
                "time": epoch, "open": float(row["Open"]), "high": float(row["High"]),
                "low": float(row["Low"]), "close": float(row["Close"]),
                "volume": int(row["Volume"]) if "Volume" in row and pd.notna(row["Volume"]) else 0,
            })
        return {"symbol": symbol, "instrument_id": instrument.id if instrument else None, "ohlcv": candles}
    except HTTPException:
        raise
    except Exception as exc:
        raise _error(503, "history_unavailable", str(exc))


@app.get("/api/annotations")
def annotations(symbol: str):
    conn = db.get_db()
    rows = conn.execute("SELECT * FROM annotations WHERE symbol=? ORDER BY created_at", (symbol,)).fetchall()
    conn.close()
    result = []
    for row in rows:
        item = dict(row)
        item["data"] = json.loads(item["data"])
        result.append(item)
    return result


@app.post("/api/annotations")
def create_annotation(request: NewAnnotation):
    annotation_id = f"ann_{uuid.uuid4().hex[:8]}"
    conn = db.get_db()
    conn.execute(
        "INSERT INTO annotations(id,symbol,type,data,color,created_at) VALUES(?,?,?,?,?,?)",
        (annotation_id, request.symbol, request.type, json.dumps(request.data), request.color, _now()),
    )
    conn.commit()
    conn.close()
    return {"id": annotation_id, "status": "created"}


@app.delete("/api/annotations/{annotation_id}")
def delete_annotation(annotation_id: str):
    conn = db.get_db()
    result = conn.execute("DELETE FROM annotations WHERE id=?", (annotation_id,))
    conn.commit()
    conn.close()
    if not result.rowcount:
        raise _error(404, "annotation_not_found", "Annotation not found")
    return {"status": "deleted"}


@app.get("/api/trade-ideas/stats")
def idea_stats():
    conn = db.get_db()
    rows = [dict(row) for row in conn.execute("SELECT * FROM trade_ideas").fetchall()]
    conn.close()
    scored = [row for row in rows if row.get("review_state") == "scored" and row["outcome_pnl"] is not None]
    wins = [row for row in scored if row["outcome_pnl"] > 0]
    losses = [row for row in scored if row["outcome_pnl"] < 0]
    return {
        "total": len(rows), "active": sum(row["status"] == "active" for row in rows),
        "closed": sum(row["status"] == "closed" for row in rows), "scored": len(scored),
        "unscored": sum(row.get("review_state") == "unscored" for row in rows),
        "needs_review": sum(row.get("review_state") in ("invalid", "stale", "needs_review") for row in rows),
        "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / max(len(wins) + len(losses), 1) * 100,
        "avg_pnl": sum(row["outcome_pnl"] for row in scored) / len(scored) if scored else 0,
    }


@app.get("/api/whales")
def whales():
    try:
        from whales import get_whale_signals
        return get_whale_signals(["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD"])
    except Exception:
        return []
