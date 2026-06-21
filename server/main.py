import uuid
import json
import requests
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from typing import Optional

import db
import prices
from agent import agent

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield

app = FastAPI(title="NEXUS Trading API", lifespan=lifespan)

# CORS configuration - restrict in production
# For development, allow localhost origins. In production, specify exact origins.
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ── Models ──

class NewPosition(BaseModel):
    pair: str
    asset_class: str
    side: str
    size: float
    confidence: float = 0.7

    @field_validator("size")
    @classmethod
    def validate_size(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Size must be positive")
        if v > 1_000_000_000:
            raise ValueError("Size exceeds maximum allowed")
        return v

class NewLog(BaseModel):
    level: str
    action: str
    pair: Optional[str] = None
    message: str

# ── Helpers ──

def _now():
    return datetime.now(timezone.utc).isoformat()

def _notional(p: dict, price_data: dict) -> float:
    pair = p["pair"]
    size = abs(p["size"])
    if p["asset_class"] == "forex" and "/" in pair:
        base, quote = pair.split("/")
        if base == "USD":
            return size
        usd_rate = price_data.get(f"{base}/USD", {}).get("price")
        if usd_rate:
            return size * usd_rate
        return size * p["current_price"] if quote == "USD" else size
    return size * p["current_price"]

def _calc_pnl(p: dict, price_data: dict) -> float:
    direction = 1 if p["side"] == "long" else -1
    raw = (p["current_price"] - p["entry_price"]) * p["size"] * direction
    if p["asset_class"] == "forex" and "/" in p["pair"]:
        base, quote = p["pair"].split("/")
        if quote == "USD":
            return raw
        if base == "USD" and p["current_price"] > 0:
            return raw / p["current_price"]
        if p["current_price"] > 0:
            quote_usd = price_data.get(f"{quote}/USD", {}).get("price")
            if quote_usd:
                return raw / p["current_price"] * quote_usd
            usd_quote = price_data.get(f"USD/{quote}", {}).get("price")
            if usd_quote and usd_quote > 0:
                return raw / p["current_price"] / usd_quote
    return raw

def _position_with_price(row: dict, price_data: dict) -> dict:
    p = dict(row)
    pair = p["pair"]
    pd = price_data.get(pair)
    current = pd["price"] if pd else p["entry_price"]
    p["current_price"] = current
    direction = 1 if p["side"] == "long" else -1
    p["pnl"] = _calc_pnl(p, price_data)
    p["pnl_pct"] = ((current - p["entry_price"]) / p["entry_price"]) * 100 * direction if p["entry_price"] else 0
    p["notional"] = _notional(p, price_data)
    return p

# ── Endpoints ──

@app.get("/api/health")
def health():
    return {"status": "ok", "time": _now()}

@app.get("/api/watchlist")
def get_watchlist():
    from agent import WATCHLIST
    symbols = [p for p, _ in WATCHLIST]
    price_data = prices.fetch_prices(symbols)
    result = []
    for pair, asset_class in WATCHLIST:
        pd = price_data.get(pair)
        result.append({
            "pair": pair,
            "asset_class": asset_class,
            "price": pd["price"] if pd else None,
            "change_pct": pd["changePct"] if pd else None,
        })
    return result

@app.get("/api/prices")
def get_prices(symbols: str = ""):
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not sym_list:
        return {}
    return prices.fetch_prices(sym_list)

@app.get("/api/positions")
def get_positions():
    conn = db.get_db()
    rows = conn.execute("SELECT * FROM positions").fetchall()
    conn.close()
    if not rows:
        return []
    pairs = [r["pair"] for r in rows]
    price_data = prices.fetch_prices(pairs)
    return [_position_with_price(r, price_data) for r in rows]

@app.post("/api/positions")
def open_position(pos: NewPosition):
    entry_price = prices.fetch_single(pos.pair)
    if entry_price is None:
        raise HTTPException(400, f"Could not fetch price for {pos.pair}")
    pos_id = f"p{uuid.uuid4().hex[:6]}"
    conn = db.get_db()
    conn.execute(
        "INSERT INTO positions VALUES (?,?,?,?,?,?,?,?)",
        (pos_id, pos.pair, pos.asset_class, pos.side, pos.size, entry_price, _now(), pos.confidence),
    )
    log_id = f"l{uuid.uuid4().hex[:6]}"
    conn.execute(
        "INSERT INTO logs VALUES (?,?,?,?,?,?)",
        (log_id, "info", "OPEN", pos.pair,
         f"Opened {pos.side} {pos.size} {pos.pair} @ {entry_price}. Confidence {pos.confidence}.",
         _now()),
    )
    conn.commit()
    conn.close()
    return {"id": pos_id, "entry_price": entry_price}

@app.delete("/api/positions/{pos_id}")
def close_position(pos_id: str):
    conn = db.get_db()
    row = conn.execute("SELECT * FROM positions WHERE id = ?", (pos_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Position not found")
    exit_price = prices.fetch_single(row["pair"])
    if exit_price is None:
        conn.close()
        raise HTTPException(400, f"Could not fetch price for {row['pair']}")
    direction = 1 if row["side"] == "long" else -1
    raw_pnl = (exit_price - row["entry_price"]) * row["size"] * direction
    pnl = raw_pnl
    if row["asset_class"] == "forex" and "/" in row["pair"]:
        base, quote = row["pair"].split("/")
        if quote == "USD":
            pass  # raw_pnl is already in USD
        elif base == "USD" and exit_price > 0:
            pnl = raw_pnl / exit_price
        elif exit_price > 0:
            extra_pairs = [f"{quote}/USD", f"USD/{quote}"]
            extra_prices = prices.fetch_prices(extra_pairs)
            quote_usd = extra_prices.get(f"{quote}/USD", {}).get("price")
            if quote_usd:
                pnl = raw_pnl / exit_price * quote_usd
            else:
                usd_quote = extra_prices.get(f"USD/{quote}", {}).get("price")
                if usd_quote and usd_quote > 0:
                    pnl = raw_pnl / exit_price / usd_quote
    trade_id = f"t{uuid.uuid4().hex[:6]}"
    conn.execute(
        "INSERT INTO trades VALUES (?,?,?,?,?,?,?,?)",
        (trade_id, row["pair"], row["side"], row["size"], row["entry_price"], exit_price, pnl, _now()),
    )
    conn.execute("DELETE FROM positions WHERE id = ?", (pos_id,))
    log_id = f"l{uuid.uuid4().hex[:6]}"
    conn.execute(
        "INSERT INTO logs VALUES (?,?,?,?,?,?)",
        (log_id, "info", "CLOSE", row["pair"],
         f"Closed {row['side']} {row['size']} {row['pair']} @ {exit_price}. P&L: {pnl:+.2f}.",
         _now()),
    )
    conn.commit()
    conn.close()
    return {"trade_id": trade_id, "pnl": pnl}

@app.get("/api/trades")
def get_trades():
    conn = db.get_db()
    rows = conn.execute("SELECT * FROM trades ORDER BY closed_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/logs")
def get_logs(limit: int = 50):
    conn = db.get_db()
    rows = conn.execute("SELECT * FROM logs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/logs")
def add_log(entry: NewLog):
    log_id = f"l{uuid.uuid4().hex[:6]}"
    conn = db.get_db()
    conn.execute(
        "INSERT INTO logs VALUES (?,?,?,?,?,?)",
        (log_id, entry.level, entry.action, entry.pair, entry.message, _now()),
    )
    conn.commit()
    conn.close()
    return {"id": log_id}

@app.delete("/api/logs")
def clear_logs():
    conn = db.get_db()
    conn.execute("DELETE FROM logs")
    conn.commit()
    conn.close()
    return {"status": "cleared"}

@app.get("/api/portfolio")
def get_portfolio():
    conn = db.get_db()
    positions = conn.execute("SELECT * FROM positions").fetchall()
    trades = conn.execute("SELECT * FROM trades ORDER BY closed_at ASC").fetchall()
    equity_row = conn.execute("SELECT value FROM portfolio_config WHERE key = 'starting_equity'").fetchone()
    conn.close()

    starting_equity = float(equity_row["value"]) if equity_row else 100_000

    pairs = [p["pair"] for p in positions]
    price_data = prices.fetch_prices(pairs) if pairs else {}

    enriched = [_position_with_price(p, price_data) for p in positions]

    open_pnl = sum(p["pnl"] for p in enriched)
    realized = sum(t["pnl"] for t in trades)
    exposure = sum(p["notional"] for p in enriched)
    equity = starting_equity + realized + open_pnl
    leverage = exposure / max(equity, 1)

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    win_rate = (len(wins) / len(trades) * 100) if trades else 0
    avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
    avg_loss = abs(sum(t["pnl"] for t in losses) / len(losses)) if losses else 0

    eq = starting_equity
    equity_series = []
    sorted_trades = sorted(trades, key=lambda t: t["closed_at"])
    if sorted_trades:
        equity_series.append({"t": sorted_trades[0]["closed_at"], "eq": eq})
    for t in sorted_trades:
        eq += t["pnl"]
        equity_series.append({"t": t["closed_at"], "eq": eq})
    equity_series.append({"t": _now(), "eq": eq + open_pnl})

    peak = -float("inf")
    max_dd = 0
    for pt in equity_series:
        peak = max(peak, pt["eq"])
        max_dd = min(max_dd, (pt["eq"] - peak) / peak if peak > 0 else 0)

    daily_map: dict[str, float] = {}
    for t in trades:
        day = t["closed_at"][:10]
        daily_map[day] = daily_map.get(day, 0) + t["pnl"]
    daily_pnl = [{"d": k, "v": v} for k, v in sorted(daily_map.items())]

    asset_map: dict[str, dict] = {}
    for p in enriched:
        ac = p["asset_class"]
        if ac not in asset_map:
            asset_map[ac] = {"exposure": 0, "pnl": 0, "count": 0}
        asset_map[ac]["exposure"] += p["notional"]
        asset_map[ac]["pnl"] += p["pnl"]
        asset_map[ac]["count"] += 1
    total_exp = sum(a["exposure"] for a in asset_map.values()) or 1
    by_asset = [
        {"k": ac, **vals, "pct": vals["exposure"] / total_exp * 100}
        for ac, vals in asset_map.items()
    ]

    alloc_map: dict[str, float] = {}
    for p in enriched:
        key = p["pair"].split("/")[0] if "/" in p["pair"] else p["pair"]
        alloc_map[key] = alloc_map.get(key, 0) + p["notional"]
    total_alloc = sum(alloc_map.values()) or 1
    allocation = [
        {"ccy": k, "value": v, "pct": v / total_alloc * 100}
        for k, v in sorted(alloc_map.items(), key=lambda x: -x[1])
    ]

    winners = sorted(enriched, key=lambda p: -p["pnl"])[:3]
    losers = sorted(enriched, key=lambda p: p["pnl"])[:3]

    profit_factor = (avg_win * len(wins) / (avg_loss * max(len(losses), 1))) if avg_loss > 0 and losses else (999.99 if wins else 0)

    return {
        "starting_equity": starting_equity,
        "equity": equity,
        "open_pnl": open_pnl,
        "realized": realized,
        "exposure": exposure,
        "leverage": leverage,
        "open_count": len(enriched),
        "win_rate": win_rate,
        "wins": len(wins),
        "losses": len(losses),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "max_drawdown": max_dd * 100,
        "equity_series": equity_series,
        "daily_pnl": daily_pnl,
        "by_asset": by_asset,
        "allocation": allocation,
        "winners": winners,
        "losers": losers,
    }

@app.get("/api/agent/status")
def agent_status():
    return agent.status()

@app.post("/api/agent/start")
def agent_start(interval: int = 120):
    agent.start(interval)
    return {"status": "started", "interval": interval}

@app.post("/api/agent/stop")
def agent_stop():
    agent.stop()
    return {"status": "stopped"}

@app.post("/api/agent/trigger")
def agent_trigger():
    """Manually trigger one agent cycle (useful for testing)."""
    import threading
    threading.Thread(target=agent._run_cycle, daemon=True).start()
    return {"status": "triggered"}

# ── LLM Config ──

class LLMConfigUpdate(BaseModel):
    provider: str
    model: str
    api_key: Optional[str] = ""
    base_url: Optional[str] = ""
    num_ctx: Optional[int] = 8192

@app.get("/api/llm/config")
def get_llm_config():
    import crypto_utils
    conn = db.get_db()
    row = conn.execute("SELECT * FROM llm_config WHERE id = 1").fetchone()
    conn.close()
    if not row:
        return {"provider": "ollama", "model": "minimax-m3:cloud", "api_key": "", "base_url": "", "num_ctx": 8192}
    result = dict(row)
    if result.get("api_key"):
        decrypted = crypto_utils.decrypt(result["api_key"])
        if decrypted:
            result["api_key"] = decrypted[:8] + "..." + decrypted[-4:]
        else:
            result["api_key"] = ""
    if "num_ctx" not in result:
        result["num_ctx"] = 8192
    return result

@app.put("/api/llm/config")
def update_llm_config(config: LLMConfigUpdate):
    import llm as llm_module
    import crypto_utils
    if config.provider not in llm_module.PROVIDERS:
        raise HTTPException(400, f"Unknown provider: {config.provider}. Valid: {list(llm_module.PROVIDERS.keys())}")

    encrypted_key = crypto_utils.encrypt(config.api_key) if config.api_key else ""

    conn = db.get_db()
    conn.execute(
        "INSERT INTO llm_config (id, provider, model, api_key, base_url, num_ctx) VALUES (1, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET provider=excluded.provider, model=excluded.model, "
        "api_key=excluded.api_key, base_url=excluded.base_url, num_ctx=excluded.num_ctx",
        (config.provider, config.model, encrypted_key, config.base_url or "", config.num_ctx or 8192),
    )
    conn.commit()
    conn.close()

    agent.reload_provider()
    return {"status": "updated", "provider": config.provider, "model": config.model}

@app.get("/api/llm/providers")
def list_llm_providers():
    import llm as llm_module
    result = {}
    for key, info in llm_module.PROVIDERS.items():
        result[key] = {
            "name": info["name"],
            "needs_key": info["needs_key"],
            "models": info["models"],
        }
    return result

_LMSTUDIO_CACHE: dict = {"models": [], "time": 0}

@app.get("/api/llm/lmstudio/models")
def list_lmstudio_models():
    import time as _time
    now = _time.time()
    if now - _LMSTUDIO_CACHE["time"] < 60 and _LMSTUDIO_CACHE["models"]:
        return {"models": _LMSTUDIO_CACHE["models"]}
    try:
        resp = requests.get("http://localhost:1234/api/v1/models", timeout=2)
        resp.raise_for_status()
        data = resp.json()
        # LMStudio format: {"models": [{"key": "...", ...}]}
        if "models" in data:
            models = [m.get("key") or m.get("id", "") for m in data["models"]]
        # OpenAI format: {"data": [{"id": "..."}]}
        elif "data" in data:
            models = [m["id"] for m in data["data"]]
        else:
            models = []
        models = [m for m in models if m]
        _LMSTUDIO_CACHE["models"] = models
        _LMSTUDIO_CACHE["time"] = now
        return {"models": models}
    except Exception as e:
        return {"models": [], "error": str(e)}

# ── Portfolio Config ──

class ConfigUpdate(BaseModel):
    starting_equity: Optional[float] = None
    display_currency: Optional[str] = None
    risk_profile: Optional[str] = None
    allowed_asset_classes: Optional[str] = None
    exposure_limit: Optional[float] = None

_FX_CACHE: dict[str, tuple[float, float]] = {}
_FX_TTL = 300

def _get_fx_rate(currency: str) -> float:
    """Get USD-to-currency exchange rate. Returns 1.0 for USD."""
    import time
    if currency == "USD":
        return 1.0
    now = time.time()
    cached = _FX_CACHE.get(currency)
    if cached and now - cached[1] < _FX_TTL:
        return cached[0]
    pair = f"USD/{currency}"
    rate = prices.fetch_single(pair)
    if rate:
        _FX_CACHE[currency] = (rate, now)
        return rate
    return 1.0

@app.get("/api/config")
def get_config():
    conn = db.get_db()
    equity_row = conn.execute("SELECT value FROM portfolio_config WHERE key = 'starting_equity'").fetchone()
    currency_row = conn.execute("SELECT value FROM portfolio_config WHERE key = 'display_currency'").fetchone()
    risk_row = conn.execute("SELECT value FROM portfolio_config WHERE key = 'risk_profile'").fetchone()
    ac_row = conn.execute("SELECT value FROM portfolio_config WHERE key = 'allowed_asset_classes'").fetchone()
    el_row = conn.execute("SELECT value FROM portfolio_config WHERE key = 'exposure_limit'").fetchone()
    conn.close()
    currency = currency_row["value"] if currency_row else "USD"
    fx_rate = _get_fx_rate(currency)
    return {
        "starting_equity": float(equity_row["value"]) if equity_row else 100_000,
        "display_currency": currency,
        "fx_rate": fx_rate,
        "risk_profile": risk_row["value"] if risk_row else "moderate",
        "allowed_asset_classes": ac_row["value"] if ac_row else "forex,stock,crypto,cfd,futures",
        "exposure_limit": float(el_row["value"]) if el_row else 80,
    }

@app.put("/api/config")
def update_config(config: ConfigUpdate):
    conn = db.get_db()
    if config.starting_equity is not None:
        if config.starting_equity <= 0:
            conn.close()
            raise HTTPException(400, "Starting equity must be positive")
        conn.execute(
            "INSERT INTO portfolio_config (key, value) VALUES ('starting_equity', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(config.starting_equity),),
        )
    if config.display_currency is not None:
        if config.display_currency not in ("USD", "CZK"):
            conn.close()
            raise HTTPException(400, "Supported currencies: USD, CZK")
        conn.execute(
            "INSERT INTO portfolio_config (key, value) VALUES ('display_currency', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (config.display_currency,),
        )
    if config.risk_profile is not None:
        if config.risk_profile not in ("conservative", "moderate", "aggressive"):
            conn.close()
            raise HTTPException(400, "Valid profiles: conservative, moderate, aggressive")
        conn.execute(
            "INSERT INTO portfolio_config (key, value) VALUES ('risk_profile', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (config.risk_profile,),
        )
    if config.allowed_asset_classes is not None:
        valid = set(("forex", "stock", "crypto", "cfd", "futures"))
        classes = [c.strip() for c in config.allowed_asset_classes.split(",") if c.strip() in valid]
        if not classes:
            conn.close()
            raise HTTPException(400, "Must include at least one of: forex, stock, crypto, cfd")
        conn.execute(
            "INSERT INTO portfolio_config (key, value) VALUES ('allowed_asset_classes', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (",".join(classes),),
        )
    if config.exposure_limit is not None:
        if config.exposure_limit < 0:
            conn.close()
            raise HTTPException(400, "Exposure limit must be non-negative")
        conn.execute(
            "INSERT INTO portfolio_config (key, value) VALUES ('exposure_limit', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(config.exposure_limit),),
        )
    conn.commit()
    conn.close()
    agent.reload_config()
    return {"status": "updated"}

# ── Trade Ideas ──

class NewTradeIdea(BaseModel):
    symbol: str
    asset_class: str
    side: str
    entry_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    confidence: Optional[float] = None
    reasoning: Optional[str] = None

@app.get("/api/trade-ideas")
def list_trade_ideas(status: Optional[str] = None):
    conn = db.get_db()
    if status:
        rows = conn.execute(
            "SELECT * FROM trade_ideas WHERE status = ? ORDER BY created_at DESC",
            (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM trade_ideas ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.post("/api/trade-ideas")
def create_trade_idea(idea: NewTradeIdea):
    idea_id = f"idea_{uuid.uuid4().hex[:8]}"
    conn = db.get_db()
    conn.execute(
        """INSERT INTO trade_ideas 
           (id, symbol, asset_class, side, entry_price, stop_loss, take_profit, 
            confidence, reasoning, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)""",
        (idea_id, idea.symbol, idea.asset_class, idea.side, idea.entry_price,
         idea.stop_loss, idea.take_profit, idea.confidence, idea.reasoning, _now())
    )
    conn.commit()
    conn.close()
    return {"id": idea_id, "status": "created"}

@app.put("/api/trade-ideas/{idea_id}/close")
def close_trade_idea(idea_id: str, outcome_pnl: Optional[float] = None):
    conn = db.get_db()
    result = conn.execute(
        """UPDATE trade_ideas 
           SET status = 'closed', closed_at = ?, outcome_pnl = ?
           WHERE id = ? AND status = 'active'""",
        (_now(), outcome_pnl, idea_id)
    )
    conn.commit()
    conn.close()
    if result.rowcount == 0:
        raise HTTPException(404, "Trade idea not found or already closed")
    return {"status": "closed"}

_GENERATE_IDEA_RATE_LIMIT: dict[str, float] = {}
_RATE_LIMIT_WINDOW = 10  # seconds between requests per symbol

@app.post("/api/trade-ideas/generate")
def generate_trade_idea(symbol: str, timeframe: str = "swing"):
    """Ask the AI to analyze a symbol and create a trade idea with entry/SL/TP."""
    import time

    # Rate limiting
    now = time.time()
    rate_key = f"{symbol}_{timeframe}"
    last_request = _GENERATE_IDEA_RATE_LIMIT.get(rate_key, 0)
    if now - last_request < _RATE_LIMIT_WINDOW:
        raise HTTPException(429, f"Rate limit: Wait {_RATE_LIMIT_WINDOW - (now - last_request):.1f}s before requesting {symbol} again")
    _GENERATE_IDEA_RATE_LIMIT[rate_key] = now
    
    import context as ctx
    
    # Find asset class for symbol
    from agent import WATCHLIST
    asset_class = "stock"
    for s, ac in WATCHLIST:
        if s == symbol:
            asset_class = ac
            break
    
    # Build technical context for this symbol
    market_context = ctx.build_market_context([symbol], [asset_class])
    
    # Get current price
    current_price = prices.fetch_single(symbol)
    if current_price is None:
        raise HTTPException(400, f"Could not fetch price for {symbol}")
    
    # Build focused prompt
    if timeframe == "scalp":
        tf_rules = """This is a SCALP / QUICK trade (hold minutes to hours).
- Focus on short-term momentum, RSI extremes, MACD crossovers, Bollinger Band bounces
- Stop loss = entry - (1 x ATR) for long, entry + (1 x ATR) for short
- Take profit = entry + (1.5 x ATR) for long, entry - (1.5 x ATR) for short
- Prefer setups near support/resistance with tight risk
- High confidence only if multiple short-term signals align"""
    else:
        tf_rules = """This is a SWING / LONG-TERM trade (hold days to weeks).
- Focus on trend direction (SMA 20/50 alignment), weekly momentum, news sentiment
- Stop loss = entry - (2 x ATR) for long, entry + (2 x ATR) for short
- Take profit = entry + (4 x ATR) for long, entry - (4 x ATR) for short
- Prefer setups in the direction of the major trend
- Consider fundamental catalysts (sector strength, macro environment)"""

    prompt = f"""Analyze {symbol} ({asset_class}) and create a {timeframe} trade idea with exact price levels.

Current price: {current_price}

Technical data:
{market_context}

{tf_rules}

You MUST create a trade setup. Choose the direction (long or short) that has the strongest technical support, even if signals are weak. Only refuse if there is absolutely no price data.

Respond with ONLY valid JSON (no markdown, no explanation):
{{
  "side": "long" or "short",
  "confidence": 0.0 to 1.0,
  "stop_loss": exact price level,
  "take_profit": exact price level,
  "reason": "brief reason for this setup"
}}

If ATR data is missing, use 2% of entry price as ATR estimate.
"""
    
    # Call the AI
    try:
        provider = agent._provider
        if not provider:
            raise HTTPException(500, "No LLM provider configured")
        
        result = provider.chat("You are a trading analyst. Create precise trade setups with exact price levels.", prompt)
        
        # Parse the response
        import json, re
        cleaned = result.strip()
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", cleaned).strip()
        if cleaned.startswith("```"):
            first_nl = cleaned.index("\n") if "\n" in cleaned else 3
            cleaned = cleaned[first_nl + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        cleaned = re.sub(r"//[^\n]*", "", cleaned)
        # Remove trailing commas before } or ]
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)

        decision = None
        # Strategy 1: direct parse
        try:
            decision = json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Strategy 2: extract first JSON object
        if decision is None:
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if match:
                try:
                    decision = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        # Strategy 3: fix single quotes and retry
        if decision is None:
            fixed = cleaned.replace("'", '"')
            try:
                decision = json.loads(fixed)
            except json.JSONDecodeError:
                match = re.search(r"\{[\s\S]*\}", fixed)
                if match:
                    try:
                        decision = json.loads(match.group())
                    except json.JSONDecodeError:
                        pass

        if decision is None:
            raise HTTPException(500, f"Could not parse AI response: {result[:300]}")
        
        if decision.get("side") is None:
            return {"status": "no_setup", "reason": decision.get("reason", "No valid setup found")}
        
        # Create the trade idea
        idea_id = f"idea_{uuid.uuid4().hex[:8]}"
        conn = db.get_db()
        conn.execute(
            """INSERT INTO trade_ideas 
               (id, symbol, asset_class, side, entry_price, stop_loss, take_profit, 
                confidence, reasoning, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)""",
            (idea_id, symbol, asset_class, decision.get("side", "long"), current_price,
             decision.get("stop_loss"), decision.get("take_profit"),
             decision.get("confidence", 0.7), decision.get("reason", ""),
             _now())
        )
        conn.commit()
        conn.close()
        
        return {
            "id": idea_id,
            "status": "created",
            "symbol": symbol,
            "side": decision.get("side"),
            "entry_price": current_price,
            "stop_loss": decision.get("stop_loss"),
            "take_profit": decision.get("take_profit"),
            "confidence": decision.get("confidence"),
            "reason": decision.get("reason"),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to generate trade idea: {str(e)}")

@app.get("/api/trade-ideas/ohlcv")
def get_ohlcv(symbol: str, period: str = "5d", interval: str = "15m"):
    import yfinance as yf
    import pandas as pd
    
    # Map interval to max allowed period
    interval_periods = {"1m": "7d", "5m": "60d", "15m": "60d", "30m": "60d", "1h": "730d", "1d": "3mo"}
    if period == "auto":
        period = interval_periods.get(interval, "5d")
    
    yf_symbol = prices.pair_to_yfinance(symbol)
    
    try:
        df = yf.download(yf_symbol, period=period, interval=interval, auto_adjust=True, progress=False)
        
        if df is None or df.empty:
            raise HTTPException(404, f"No data found for {symbol}")
        
        # Handle MultiIndex columns
        if isinstance(df.columns, pd.MultiIndex):
            # Check if level 0 has the ticker (multi-symbol download)
            if yf_symbol in df.columns.get_level_values(0):
                df = df[yf_symbol]
            # Check if level 1 has the ticker (single-symbol download)
            elif yf_symbol in df.columns.get_level_values(1):
                df = df.xs(yf_symbol, level=1, axis=1)
            else:
                # Try to squeeze - might work for single symbol
                try:
                    df = df.droplevel(1, axis=1)
                except Exception:
                    raise HTTPException(404, f"No data found for {symbol}")
        
        df = df.dropna(subset=["Close"])
        if df.empty:
            raise HTTPException(404, f"No valid data for {symbol}")
        df = df.sort_index()
        
        ohlcv = []
        for timestamp, row in df.iterrows():
            ts = timestamp.to_pydatetime() if hasattr(timestamp, 'to_pydatetime') else timestamp
            if hasattr(ts, 'tzinfo') and ts.tzinfo:
                ts = ts.replace(tzinfo=None)
            ohlcv.append({
                "time": int(ts.timestamp()),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]) if "Volume" in row and pd.notna(row["Volume"]) else 0
            })
        
        return {"symbol": symbol, "ohlcv": ohlcv}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch OHLCV data: {str(e)}")

# ── Annotations ──

class NewAnnotation(BaseModel):
    symbol: str
    type: str  # "hline", "trendline", "zone", "text"
    data: dict
    color: Optional[str] = None

@app.get("/api/annotations")
def get_annotations(symbol: str):
    conn = db.get_db()
    rows = conn.execute(
        "SELECT * FROM annotations WHERE symbol = ? ORDER BY created_at ASC",
        (symbol,)
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        item = dict(row)
        item["data"] = json.loads(item["data"])
        result.append(item)
    return result

@app.post("/api/annotations")
def create_annotation(annotation: NewAnnotation):
    ann_id = f"ann_{uuid.uuid4().hex[:8]}"
    conn = db.get_db()
    conn.execute(
        "INSERT INTO annotations (id, symbol, type, data, color, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (ann_id, annotation.symbol, annotation.type, json.dumps(annotation.data), annotation.color, _now())
    )
    conn.commit()
    conn.close()
    return {"id": ann_id, "status": "created"}

@app.delete("/api/annotations/{ann_id}")
def delete_annotation(ann_id: str):
    conn = db.get_db()
    result = conn.execute("DELETE FROM annotations WHERE id = ?", (ann_id,))
    conn.commit()
    conn.close()
    if result.rowcount == 0:
        raise HTTPException(404, "Annotation not found")
    return {"status": "deleted"}

@app.get("/api/trade-ideas/stats")
def get_trade_idea_stats():
    conn = db.get_db()
    total = conn.execute("SELECT COUNT(*) as c FROM trade_ideas").fetchone()["c"]
    closed = conn.execute("SELECT COUNT(*) as c FROM trade_ideas WHERE status = 'closed'").fetchone()["c"]
    active = conn.execute("SELECT COUNT(*) as c FROM trade_ideas WHERE status = 'active'").fetchone()["c"]
    
    wins = conn.execute("SELECT COUNT(*) as c FROM trade_ideas WHERE status = 'closed' AND outcome_pnl > 0").fetchone()["c"]
    losses = conn.execute("SELECT COUNT(*) as c FROM trade_ideas WHERE status = 'closed' AND outcome_pnl <= 0").fetchone()["c"]
    
    avg_pnl_row = conn.execute("SELECT AVG(outcome_pnl) as avg FROM trade_ideas WHERE status = 'closed' AND outcome_pnl IS NOT NULL").fetchone()
    avg_pnl = avg_pnl_row["avg"] if avg_pnl_row["avg"] else 0
    
    hit_tp = conn.execute("SELECT COUNT(*) as c FROM trade_ideas WHERE status = 'closed' AND outcome_pnl > 0").fetchone()["c"]
    hit_sl = conn.execute("SELECT COUNT(*) as c FROM trade_ideas WHERE status = 'closed' AND outcome_pnl < 0").fetchone()["c"]
    
    # Breakdown by asset class
    by_asset_rows = conn.execute("""
        SELECT asset_class, 
               COUNT(*) as total,
               SUM(CASE WHEN outcome_pnl > 0 THEN 1 ELSE 0 END) as wins,
               AVG(outcome_pnl) as avg_pnl
        FROM trade_ideas 
        WHERE status = 'closed' 
        GROUP BY asset_class
    """).fetchall()
    by_asset = [dict(r) for r in by_asset_rows]
    
    # Breakdown by side
    by_side_rows = conn.execute("""
        SELECT side, 
               COUNT(*) as total,
               SUM(CASE WHEN outcome_pnl > 0 THEN 1 ELSE 0 END) as wins,
               AVG(outcome_pnl) as avg_pnl
        FROM trade_ideas 
        WHERE status = 'closed' 
        GROUP BY side
    """).fetchall()
    by_side = [dict(r) for r in by_side_rows]
    
    # Recent performance (last 20 closed)
    recent_rows = conn.execute("""
        SELECT symbol, side, outcome_pnl, created_at, closed_at
        FROM trade_ideas 
        WHERE status = 'closed' AND outcome_pnl IS NOT NULL
        ORDER BY closed_at DESC 
        LIMIT 20
    """).fetchall()
    recent = [dict(r) for r in recent_rows]
    
    # Equity curve from closed ideas
    equity_rows = conn.execute("""
        SELECT outcome_pnl, closed_at
        FROM trade_ideas 
        WHERE status = 'closed' AND outcome_pnl IS NOT NULL
        ORDER BY closed_at ASC
    """).fetchall()
    equity_curve = []
    cumulative = 0
    for r in equity_rows:
        cumulative += r["outcome_pnl"]
        equity_curve.append({"t": r["closed_at"], "pnl": cumulative})
    
    conn.close()
    
    win_rate = (wins / closed * 100) if closed > 0 else 0
    
    return {
        "total": total,
        "active": active,
        "closed": closed,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_pnl": avg_pnl,
        "hit_tp": hit_tp,
        "hit_sl": hit_sl,
        "by_asset": by_asset,
        "by_side": by_side,
        "recent": recent,
        "equity_curve": equity_curve,
    }

# ── Whale Activity ──

@app.get("/api/whales")
def get_whales():
    import whales as whales_module
    signals = whales_module.get_whale_signals()
    return signals

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
