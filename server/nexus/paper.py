"""Paper broker: positions, fills, exits and portfolio accounting.

Fills use the latest delayed quote plus slippage. Orders placed while a market is
closed (or the quote is stale) wait as `pending` and fill at the first fresh quote
after the open. Stops/targets are checked against live quotes and against daily
bar highs/lows (a gap through a stop fills at the bar's open, not the stop).

Correlated risk: each position risks about one risk budget. Before opening, positions
whose 60-day daily returns move with the new one (correlation adjusted for long/short)
count as part of the same bet; the order is refused when that bet would exceed
`max_correlated_risk` budgets (default 2: the new trade plus one equivalent).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import numpy as np

from . import config, data, db, universe
from .ingest import prices

SLIPPAGE_BPS = {"stock": 2.0, "etf": 1.0, "crypto": 10.0, "forex": 1.0, "commodity": 3.0}
FEE_BPS = {"stock": 0.0, "etf": 0.0, "crypto": 10.0, "forex": 0.0, "commodity": 1.0}
MAX_POSITION_PCT = 0.25
CORRELATION_DAYS = 60
SAME_BET_RHO = 0.5


def _usd_per_unit_move(item: universe.Instrument, price: float) -> float:
    """USD P&L of a 1.0 price move on one unit (handles non-USD-quoted FX pairs)."""
    if item.quote_currency == "USD":
        return item.multiplier
    if item.symbol.startswith("USD/") and price:
        return item.multiplier / price
    return item.multiplier


def pnl(item: universe.Instrument, side: str, quantity: float, entry: float, exit_price: float) -> float:
    direction = 1 if side == "long" else -1
    return (exit_price - entry) * quantity * direction * _usd_per_unit_move(item, exit_price)


def notional(item: universe.Instrument, quantity: float, price: float) -> float:
    if item.asset_class == "forex":
        base = item.symbol.split("/")[0]
        return abs(quantity) if base == "USD" else abs(quantity * price * _usd_per_unit_move(item, price))
    return abs(quantity * price * item.multiplier)


def _fill_price(item: universe.Instrument, side: str, price: float, opening: bool) -> float:
    direction = 1 if (side == "long") == opening else -1
    return price * (1 + direction * SLIPPAGE_BPS[item.asset_class] / 10_000)


def _fee(item: universe.Instrument, quantity: float, price: float) -> float:
    return notional(item, quantity, price) * FEE_BPS[item.asset_class] / 10_000


# ── Sizing & orders ──────────────────────────────────────────────────────────

def size_for(item: universe.Instrument, entry: float, stop: float, equity: float) -> float:
    risk_budget = equity * config.get_float("risk_per_trade")
    per_unit = abs(entry - stop) * _usd_per_unit_move(item, entry)
    if per_unit <= 0:
        return 0.0
    quantity = risk_budget / per_unit
    max_notional = equity * MAX_POSITION_PCT
    unit_notional = notional(item, 1.0, entry)
    if unit_notional and quantity * unit_notional > max_notional:
        quantity = max_notional / unit_notional
    if item.asset_class in ("stock", "etf"):
        quantity = float(int(quantity))
    elif item.asset_class == "commodity":
        quantity = float(int(quantity)) or (1.0 if unit_notional <= max_notional else 0.0)
    else:
        quantity = round(quantity, 4)
    return quantity


def correlated_risk(instrument_id: str, side: str) -> dict:
    """How much of the book is already the same bet as a new `side` position in `instrument_id`.
    rho is the side-adjusted correlation of daily returns: +1 means the two positions win and
    lose together. Risk units = 1 (the new trade) + the sum of rho over same-bet positions."""
    held = db.rows("SELECT instrument_id, side FROM positions WHERE instrument_id != ?", (instrument_id,))
    if not held:
        return {"units": 1.0, "same_bet": []}
    closes = data.closes()
    ids = [instrument_id] + [h["instrument_id"] for h in held]
    if closes.empty or instrument_id not in closes:
        return {"units": 1.0, "same_bet": []}
    returns = np.log(closes.reindex(columns=ids).tail(CORRELATION_DAYS + 1)).diff().iloc[1:]
    sign = 1 if side == "long" else -1
    same_bet = []
    for h in held:
        column = h["instrument_id"]
        pair = returns[[instrument_id, column]].dropna() if column in returns else None
        if pair is None or len(pair) < CORRELATION_DAYS // 2:
            continue
        rho = float(pair.corr().iloc[0, 1]) * sign * (1 if h["side"] == "long" else -1)
        if rho >= SAME_BET_RHO:
            item = universe.get(column)
            same_bet.append({"instrument_id": column, "symbol": item.symbol if item else column, "side": h["side"],
                             "rho": round(rho, 2)})
    same_bet.sort(key=lambda r: -r["rho"])
    return {"units": round(1.0 + sum(r["rho"] for r in same_bet), 2), "same_bet": same_bet}


def open_position(instrument_id: str, side: str, *, stop: float, target: float | None, expires_at: str | None,
                  recommendation_id: str | None = None, source: str = "manual", quantity: float | None = None) -> dict:
    item = universe.require(instrument_id)
    if not item.tradable:
        raise ValueError(f"{item.symbol} is research-only")
    snapshot = portfolio(mark=False)
    open_count = snapshot["open_count"] + snapshot["pending_count"]
    if open_count >= config.get_int("max_positions"):
        raise ValueError("Position limit reached")
    if db.one("SELECT 1 FROM positions WHERE instrument_id=?", (item.id,)):
        raise ValueError(f"Already holding {item.symbol}")
    risk = correlated_risk(item.id, side)
    limit = config.get_float("max_correlated_risk")
    if risk["units"] > limit:
        bets = ", ".join(f"{r['symbol']} {r['side']} (rho {r['rho']:.2f})" for r in risk["same_bet"])
        raise ValueError(f"Correlated risk limit: {side} {item.symbol} is the same bet as {bets}; together "
                         f"{risk['units']:.1f} risk budgets, limit {limit:g}")
    quote = prices.quote(item.id)
    reference = quote["price"] if quote and quote["price"] else None
    if reference is None:
        raise ValueError("No price available")
    if (side == "long" and stop >= reference) or (side == "short" and stop <= reference):
        raise ValueError("Stop is on the wrong side of the current price")
    qty = quantity if quantity else size_for(item, reference, stop, snapshot["equity"])
    if qty <= 0:
        raise ValueError("Position size rounds to zero for this risk budget")
    exposure_after = snapshot["exposure"] + notional(item, qty, reference)
    if exposure_after > snapshot["equity"] * config.get_float("max_exposure"):
        raise ValueError("Gross exposure limit reached")
    position_id = f"pos_{uuid.uuid4().hex[:10]}"
    db.execute(
        """INSERT INTO positions(id,instrument_id,side,quantity,status,created_at,stop,target,expires_at,recommendation_id,source)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (position_id, item.id, side, qty, "pending", db.now_iso(), stop, target, expires_at, recommendation_id, source),
    )
    _try_fill(db.one("SELECT * FROM positions WHERE id=?", (position_id,)), quote)
    db.log("info", "order", f"{side.upper()} {qty:g} {item.symbol} (stop {stop:g}, target {target}) via {source}")
    return db.one("SELECT * FROM positions WHERE id=?", (position_id,))


def _try_fill(position: dict, quote: dict | None) -> bool:
    item = universe.get(position["instrument_id"])
    if not item or not quote or quote["price"] is None or quote["stale"] or not quote["market_open"]:
        return False
    fill = _fill_price(item, position["side"], quote["price"], opening=True)
    stop = position["stop"]
    if stop is not None and ((position["side"] == "long" and fill <= stop) or (position["side"] == "short" and fill >= stop)):
        db.execute("DELETE FROM positions WHERE id=?", (position["id"],))
        db.log("warn", "order", f"Cancelled pending {item.symbol}: price already through stop at the open")
        return False
    db.execute(
        "UPDATE positions SET status='open', entry_price=?, entry_fee=?, opened_at=? WHERE id=?",
        (fill, _fee(item, position["quantity"], fill), db.now_iso(), position["id"]),
    )
    return True


def close_position(position_id: str, *, reason: str = "manual", price: float | None = None) -> dict:
    position = db.one("SELECT * FROM positions WHERE id=?", (position_id,))
    if not position:
        raise KeyError("Position not found")
    item = universe.require(position["instrument_id"])
    if position["status"] == "pending":
        db.execute("DELETE FROM positions WHERE id=?", (position_id,))
        return {"cancelled": True}
    if price is None:
        quote = prices.quote(item.id)
        if not quote or quote["price"] is None:
            raise ValueError("No price available")
        price = quote["price"]
    exit_price = _fill_price(item, position["side"], price, opening=False)
    exit_fee = _fee(item, position["quantity"], exit_price)
    gross = pnl(item, position["side"], position["quantity"], position["entry_price"], exit_price)
    fees = position["entry_fee"] + exit_fee
    trade_id = f"trd_{uuid.uuid4().hex[:10]}"
    with db.session() as conn:
        conn.execute(
            """INSERT INTO trades(id,position_id,instrument_id,side,quantity,entry_price,exit_price,opened_at,closed_at,
               gross_pnl,fees,net_pnl,exit_reason,recommendation_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (trade_id, position_id, item.id, position["side"], position["quantity"], position["entry_price"], exit_price,
             position["opened_at"], db.now_iso(), gross, fees, gross - fees, reason, position["recommendation_id"]),
        )
        conn.execute("DELETE FROM positions WHERE id=?", (position_id,))
    db.log("info", "exit", f"Closed {item.symbol} @ {exit_price:.4f} ({reason}); net {gross - fees:+.2f}")
    return {"trade_id": trade_id, "net_pnl": gross - fees, "exit_price": exit_price, "reason": reason}


# ── Monitoring ───────────────────────────────────────────────────────────────

def monitor() -> dict:
    """Fill pending orders, enforce stops/targets/expiry. Safe to run every few minutes."""
    positions = db.rows("SELECT * FROM positions")
    if not positions:
        return {"filled": 0, "closed": 0}
    quote_map = prices.quotes([row["instrument_id"] for row in positions])
    filled = closed = 0
    now = datetime.now(timezone.utc)
    for position in positions:
        quote = quote_map.get(position["instrument_id"])
        if position["status"] == "pending":
            filled += int(_try_fill(position, quote))
            continue
        exit_reason, exit_at = _exit_check(position, quote)
        if not exit_reason and position["expires_at"] and now >= datetime.fromisoformat(position["expires_at"]):
            if quote and quote["price"] is not None and quote["market_open"]:
                exit_reason, exit_at = "horizon", quote["price"]
        if exit_reason:
            try:
                close_position(position["id"], reason=exit_reason, price=exit_at)
                closed += 1
            except (KeyError, ValueError) as exc:
                db.log("warn", "monitor", f"exit failed for {position['id']}: {exc}")
    return {"filled": filled, "closed": closed}


def _exit_check(position: dict, quote: dict | None) -> tuple[str | None, float | None]:
    side, stop, target = position["side"], position["stop"], position["target"]
    opened_day = (position["opened_at"] or position["created_at"])[:10]
    bars = db.rows("SELECT open, high, low FROM bars WHERE instrument_id=? AND date>? ORDER BY date",
                   (position["instrument_id"], opened_day))
    for bar in bars:
        low, high, open_ = bar["low"], bar["high"], bar["open"] or bar["low"]
        if low is None or high is None:
            continue
        if side == "long":
            if stop is not None and low <= stop:
                return "stop", min(open_, stop)
            if target is not None and high >= target:
                return "target", max(open_, target)
        else:
            if stop is not None and high >= stop:
                return "stop", max(open_, stop)
            if target is not None and low <= target:
                return "target", min(open_, target)
    if quote and quote["price"] is not None and not quote["stale"]:
        mark = quote["price"]
        if stop is not None and ((side == "long" and mark <= stop) or (side == "short" and mark >= stop)):
            return "stop", mark
        if target is not None and ((side == "long" and mark >= target) or (side == "short" and mark <= target)):
            return "target", mark
    return None, None


# ── Portfolio ────────────────────────────────────────────────────────────────

def portfolio(*, mark: bool = True) -> dict:
    start = config.get_float("starting_equity")
    positions = db.rows("SELECT * FROM positions ORDER BY created_at DESC")
    realized = db.one("SELECT COALESCE(SUM(net_pnl),0) v FROM trades")["v"]
    quote_map = prices.quotes([row["instrument_id"] for row in positions]) if (mark and positions) else {}
    unrealized = exposure = 0.0
    out_positions = []
    for row in positions:
        item = universe.get(row["instrument_id"])
        entry = row["entry_price"]
        quote = quote_map.get(row["instrument_id"]) if mark else None
        current = quote["price"] if quote and quote["price"] is not None else entry
        open_pnl = pnl(item, row["side"], row["quantity"], entry, current) - row["entry_fee"] if (entry and current) else 0.0
        size = notional(item, row["quantity"], current or 0) if current else 0.0
        if row["status"] == "open":
            unrealized += open_pnl
            exposure += size
        direction = 1 if row["side"] == "long" else -1
        out_positions.append({
            **row, "symbol": item.symbol, "name": item.name, "asset_class": item.asset_class, "market": item.market_id,
            "current_price": current, "pnl": open_pnl, "notional": size,
            "pnl_pct": ((current / entry - 1) * 100 * direction) if (entry and current) else 0.0,
            "quote_as_of": quote.get("as_of") if quote else None,
        })
    equity = start + realized + unrealized
    trades = db.rows("SELECT net_pnl FROM trades")
    wins = [t["net_pnl"] for t in trades if t["net_pnl"] > 0]
    losses = [t["net_pnl"] for t in trades if t["net_pnl"] < 0]
    return {
        "starting_equity": start, "equity": equity, "cash": equity - exposure, "realized": realized,
        "unrealized": unrealized, "exposure": exposure, "exposure_pct": exposure / equity * 100 if equity else 0,
        "return_pct": (equity / start - 1) * 100,
        "open_count": sum(1 for p in out_positions if p["status"] == "open"),
        "pending_count": sum(1 for p in out_positions if p["status"] == "pending"),
        "trade_count": len(trades), "win_rate": len(wins) / len(trades) * 100 if trades else None,
        "avg_win": sum(wins) / len(wins) if wins else None, "avg_loss": sum(losses) / len(losses) if losses else None,
        "positions": out_positions,
    }


def snapshot_equity() -> None:
    state = portfolio()
    spy = db.one("SELECT close FROM bars WHERE instrument_id='etf:spy' ORDER BY date DESC LIMIT 1")
    db.execute(
        "INSERT OR REPLACE INTO equity_snapshots(date,equity,cash,exposure,spy_close) VALUES(?,?,?,?,?)",
        (db.today(), state["equity"], state["cash"], state["exposure"], spy["close"] if spy else None),
    )


def equity_curve() -> list[dict]:
    rows = db.rows("SELECT * FROM equity_snapshots ORDER BY date")
    if not rows:
        return []
    base_equity, base_spy = rows[0]["equity"], rows[0]["spy_close"]
    return [{
        "date": row["date"], "equity": row["equity"],
        "return_pct": (row["equity"] / base_equity - 1) * 100,
        "spy_return_pct": ((row["spy_close"] / base_spy - 1) * 100) if (row["spy_close"] and base_spy) else None,
    } for row in rows]


def expiry_from_now(horizon_days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=int(round(horizon_days * 7 / 5)))).isoformat(timespec="seconds")
