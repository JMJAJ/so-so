"""Deterministic paper execution, portfolio accounting, and protective exits."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import db
import prices
from instruments import Instrument, get_instrument, resolve_instrument


RISK_PROFILES = {
    "conservative": {"risk_per_trade": 0.005, "daily_loss": 0.02, "max_exposure": 0.50, "max_positions": 6},
    "balanced": {"risk_per_trade": 0.01, "daily_loss": 0.03, "max_exposure": 0.80, "max_positions": 10},
    "aggressive": {"risk_per_trade": 0.02, "daily_loss": 0.05, "max_exposure": 1.50, "max_positions": 12},
}
SLIPPAGE_BPS = {"stock": 2.0, "forex": 2.0, "crypto": 10.0, "cfd": 0.0, "futures": 0.0}
FEE_BPS = {"stock": 0.0, "forex": 0.0, "crypto": 10.0, "cfd": 0.0, "futures": 0.0}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _config(conn, key: str, default: str) -> str:
    row = conn.execute("SELECT value FROM portfolio_config WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def risk_profile(conn=None) -> tuple[str, dict]:
    own = conn is None
    conn = conn or db.get_db()
    name = _config(conn, "risk_profile", "balanced")
    if name == "moderate":
        name = "balanced"
    profile = RISK_PROFILES.get(name, RISK_PROFILES["balanced"])
    if own:
        conn.close()
    return name, profile


def _instrument_for_row(row) -> Instrument | None:
    instrument_id = row["instrument_id"] if "instrument_id" in row.keys() else None
    return get_instrument(instrument_id) if instrument_id else resolve_instrument(row["pair"], row["asset_class"])


def _notional(instrument: Instrument, quantity: float, price: float) -> float:
    if instrument.asset_class == "forex" and "/" in instrument.symbol:
        base, _ = instrument.symbol.split("/")
        if base == "USD":
            return abs(quantity)
        return abs(_convert_quote_pnl(instrument, quantity * price, price))
    return abs(quantity * price * instrument.multiplier)


def _convert_quote_pnl(instrument: Instrument, raw: float, current_price: float) -> float:
    if instrument.quote_currency == "USD":
        return raw
    if instrument.asset_class == "forex" and instrument.symbol.startswith("USD/") and current_price:
        return raw / current_price
    direct = resolve_instrument(f"{instrument.quote_currency}/USD", "forex")
    inverse = resolve_instrument(f"USD/{instrument.quote_currency}", "forex")
    if direct:
        quote = prices.fetch_quote(direct.id)
        if quote and quote["price"]:
            return raw * quote["price"]
    if inverse:
        quote = prices.fetch_quote(inverse.id)
        if quote and quote["price"]:
            return raw / quote["price"]
    return raw


def calculate_pnl(instrument: Instrument, side: str, quantity: float, entry: float, current: float) -> float:
    direction = 1 if side == "long" else -1
    raw = (current - entry) * quantity * instrument.multiplier * direction
    return _convert_quote_pnl(instrument, raw, current)


def _enriched_positions(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM positions ORDER BY opened_at DESC").fetchall()
    instrument_ids = [item.id for row in rows if (item := _instrument_for_row(row))]
    quote_map = prices.fetch_quotes(instrument_ids) if instrument_ids else {}
    result = []
    for row in rows:
        item = dict(row)
        instrument = _instrument_for_row(row)
        if not instrument:
            item.update({"current_price": item["entry_price"], "pnl": 0, "pnl_pct": 0, "notional": 0, "quote_stale": True})
            result.append(item)
            continue
        quote = quote_map.get(instrument.id)
        current = quote["price"] if quote and quote["price"] is not None else item["entry_price"]
        entry_fee = 0.0
        if item.get("opened_order_id"):
            order = conn.execute("SELECT fee FROM orders WHERE id=?", (item["opened_order_id"],)).fetchone()
            entry_fee = float(order["fee"] or 0) if order else 0.0
        pnl = calculate_pnl(instrument, item["side"], item["size"], item["entry_price"], current) - entry_fee
        direction = 1 if item["side"] == "long" else -1
        item.update({
            "instrument_id": instrument.id, "pair": instrument.symbol,
            "current_price": current, "pnl": pnl,
            "pnl_pct": ((current - item["entry_price"]) / item["entry_price"] * 100 * direction) if item["entry_price"] else 0,
            "notional": _notional(instrument, item["size"], current),
            "entry_fee": entry_fee,
            "quote_stale": True if not quote else quote["stale"], "quote_as_of": quote.get("as_of") if quote else None,
        })
        result.append(item)
    return result


def portfolio_snapshot(*, persist: bool = False) -> dict:
    conn = db.get_db()
    try:
        positions = _enriched_positions(conn)
        trades = [dict(row) for row in conn.execute("SELECT * FROM trades ORDER BY closed_at ASC").fetchall()]
        starting_equity = float(_config(conn, "starting_equity", "100000"))
        realized = sum(float(item["pnl"]) - float(item.get("fees") or 0) for item in trades)
        unrealized = sum(item["pnl"] for item in positions)
        gross = sum(item["notional"] for item in positions)
        equity = starting_equity + realized + unrealized
        cash = equity - gross
        today = datetime.now(timezone.utc).date().isoformat()
        realized_today = sum(
            float(item["pnl"]) - float(item.get("fees") or 0)
            for item in trades if item["closed_at"].startswith(today)
        )
        day_pnl = realized_today + unrealized
        for item in trades:
            item["net_pnl"] = float(item["pnl"]) - float(item.get("fees") or 0)
        wins = [item for item in trades if item["net_pnl"] > 0]
        losses = [item for item in trades if item["net_pnl"] < 0]
        breakeven = [item for item in trades if item["net_pnl"] == 0]
        scored = len(wins) + len(losses)
        win_rate = len(wins) / scored * 100 if scored else 0
        equity_series = [{"t": trades[0]["closed_at"], "eq": starting_equity}] if trades else []
        rolling = starting_equity
        daily: dict[str, float] = {}
        for item in trades:
            net = float(item["pnl"]) - float(item.get("fees") or 0)
            rolling += net
            equity_series.append({"t": item["closed_at"], "eq": rolling})
            day = item["closed_at"][:10]
            daily[day] = daily.get(day, 0) + net
        equity_series.append({"t": _now(), "eq": equity})
        peak, max_drawdown = starting_equity, 0.0
        for point in equity_series:
            peak = max(peak, point["eq"])
            if peak:
                max_drawdown = min(max_drawdown, (point["eq"] - peak) / peak)
        profile_name, profile = risk_profile(conn)
        by_asset: dict[str, dict] = {}
        for position in positions:
            bucket = by_asset.setdefault(position["asset_class"], {"exposure": 0.0, "pnl": 0.0, "count": 0})
            bucket["exposure"] += position["notional"]
            bucket["pnl"] += position["pnl"]
            bucket["count"] += 1
        payload = {
            "starting_equity": starting_equity, "equity": equity, "cash": cash,
            "open_pnl": unrealized, "realized": realized, "day_pnl": day_pnl,
            "exposure": gross, "gross_exposure": gross, "leverage": gross / max(equity, 1),
            "exposure_pct": gross / max(equity, 1) * 100, "open_count": len(positions),
            "win_rate": win_rate, "wins": len(wins), "losses": len(losses), "breakeven": len(breakeven),
            "avg_win": sum(item["net_pnl"] for item in wins) / len(wins) if wins else 0,
            "avg_loss": abs(sum(item["net_pnl"] for item in losses) / len(losses)) if losses else 0,
            "profit_factor": (sum(item["net_pnl"] for item in wins) / abs(sum(item["net_pnl"] for item in losses))) if losses else (999.99 if wins else 0),
            "max_drawdown": max_drawdown * 100, "equity_series": equity_series,
            "daily_pnl": [{"d": key, "v": value} for key, value in sorted(daily.items())],
            "by_asset": [{"k": key, **value, "pct": value["exposure"] / max(gross, 1) * 100} for key, value in by_asset.items()],
            "positions": positions, "risk_profile": profile_name,
            "risk_limits": profile, "risk_used_pct": gross / max(equity * profile["max_exposure"], 1) * 100,
        }
        if persist:
            latest = conn.execute("SELECT captured_at FROM equity_snapshots ORDER BY id DESC LIMIT 1").fetchone()
            should_write = not latest
            if latest:
                try:
                    then = datetime.fromisoformat(latest["captured_at"].replace("Z", "+00:00"))
                    should_write = (datetime.now(timezone.utc) - then).total_seconds() >= 60
                except ValueError:
                    should_write = True
            if should_write:
                conn.execute(
                    "INSERT INTO equity_snapshots(captured_at,equity,realized,unrealized,cash,gross_exposure) VALUES(?,?,?,?,?,?)",
                    (_now(), equity, realized, unrealized, cash, gross),
                )
                conn.commit()
        return payload
    finally:
        conn.close()


def _validation(code: str, message: str, field: str | None = None) -> dict:
    return {"code": code, "message": message, "field": field}


def _friction(instrument: Instrument, side: str, price: float, quantity: float) -> tuple[float, float, float]:
    slippage = SLIPPAGE_BPS[instrument.asset_class]
    direction = 1 if side == "long" else -1
    fill = price * (1 + direction * slippage / 10_000)
    notional = _notional(instrument, quantity, fill)
    fee = notional * FEE_BPS[instrument.asset_class] / 10_000
    return fill, notional, fee


def preview_order(payload: dict, *, source: str = "manual") -> dict:
    instrument = resolve_instrument(payload.get("instrument_id") or payload.get("symbol", ""), payload.get("asset_class"))
    errors: list[dict] = []
    warnings: list[dict] = []
    if not instrument:
        errors.append(_validation("unknown_instrument", "Instrument is not in the curated catalog.", "instrument_id"))
        return {"allowed": False, "errors": errors, "warnings": warnings}
    side = str(payload.get("side", "")).lower()
    try:
        quantity = float(payload.get("quantity", payload.get("size", 0)))
    except (TypeError, ValueError):
        quantity = 0
    stop = payload.get("stop_loss")
    target = payload.get("take_profit")
    stop = float(stop) if stop not in (None, "") else None
    target = float(target) if target not in (None, "") else None
    if instrument.eligibility != "trade_enabled":
        errors.append(_validation("research_only", "This instrument is research-only until contract metadata is verified."))
    if side not in ("long", "short"):
        errors.append(_validation("invalid_side", "Side must be long or short.", "side"))
    if quantity <= 0:
        errors.append(_validation("invalid_quantity", "Quantity must be greater than zero.", "quantity"))
    quote = prices.fetch_quote(instrument.id)
    price = quote["price"] if quote else None
    if not quote or price is None:
        errors.append(_validation("quote_unavailable", "No quote is available for this instrument."))
    elif quote["stale"]:
        errors.append(_validation("stale_quote", "The latest quote is too old to produce a trustworthy fill."))
    elif quote["market_status"] != "open":
        errors.append(_validation("market_closed", "The instrument's market is currently closed."))
    if price is not None and side in ("long", "short"):
        if stop is not None and ((side == "long" and stop >= price) or (side == "short" and stop <= price)):
            errors.append(_validation("invalid_stop", "Stop-loss is on the wrong side of the current price.", "stop_loss"))
        if target is not None and ((side == "long" and target <= price) or (side == "short" and target >= price)):
            errors.append(_validation("invalid_target", "Take-profit is on the wrong side of the current price.", "take_profit"))
    require_stop = source in ("autopilot", "proposal")
    allow_unprotected = bool(payload.get("allow_unprotected"))
    if stop is None:
        if require_stop:
            errors.append(_validation("stop_required", "Guarded AI orders require a stop-loss.", "stop_loss"))
        elif not allow_unprotected:
            errors.append(_validation("unprotected_confirmation", "Confirm that this manual paper position may be unprotected.", "allow_unprotected"))
        else:
            warnings.append(_validation("unprotected", "This position will have no automatic loss limit."))

    snapshot = portfolio_snapshot()
    conn = db.get_db()
    try:
        profile_name, profile = risk_profile(conn)
        kill_switch = _config(conn, "kill_switch", "false") == "true"
        duplicate = conn.execute("SELECT 1 FROM positions WHERE instrument_id=?", (instrument.id,)).fetchone()
    finally:
        conn.close()
    if kill_switch and source != "protective_exit":
        errors.append(_validation("kill_switch", "The kill switch blocks new entries."))
    if duplicate:
        errors.append(_validation("duplicate_position", "A position in this instrument is already open."))
    fill, notional, fee = _friction(instrument, side if side in ("long", "short") else "long", price or 0, max(quantity, 0))
    exit_fee = 0.0
    risk_amount = None
    if stop is not None:
        risk_move = abs(calculate_pnl(instrument, side, quantity, fill, stop))
        exit_fee = _notional(instrument, quantity, stop) * FEE_BPS[instrument.asset_class] / 10_000
        risk_amount = risk_move + fee + exit_fee
    resulting_exposure = snapshot["gross_exposure"] + notional
    max_risk = snapshot["equity"] * profile["risk_per_trade"]
    if risk_amount is not None and risk_amount > max_risk:
        errors.append(_validation("risk_limit", f"Estimated loss {risk_amount:.2f} exceeds the {profile_name} per-trade limit of {max_risk:.2f}."))
    if resulting_exposure > snapshot["equity"] * profile["max_exposure"]:
        errors.append(_validation("exposure_limit", f"Resulting exposure exceeds the {profile_name} limit."))
    if snapshot["open_count"] >= profile["max_positions"]:
        errors.append(_validation("position_limit", f"The {profile_name} position limit has been reached."))
    if snapshot["day_pnl"] <= -snapshot["starting_equity"] * profile["daily_loss"]:
        errors.append(_validation("daily_loss_limit", "The daily loss circuit breaker is active."))
    return {
        "allowed": not errors, "instrument": instrument.to_dict(), "side": side,
        "quantity": quantity, "quote": quote, "estimated_fill": fill,
        "notional": notional, "risk_amount": risk_amount, "fee": fee, "estimated_exit_fee": exit_fee,
        "slippage_bps": SLIPPAGE_BPS[instrument.asset_class], "resulting_exposure": resulting_exposure,
        "resulting_exposure_pct": resulting_exposure / max(snapshot["equity"], 1) * 100,
        "risk_profile": profile_name, "max_risk": max_risk,
        "stop_loss": stop, "take_profit": target, "errors": errors, "warnings": warnings,
    }


def execute_order(payload: dict, *, source: str = "manual", proposal_id: str | None = None) -> dict:
    idempotency_key = payload.get("idempotency_key")
    conn = db.get_db()
    if idempotency_key:
        existing = conn.execute("SELECT * FROM orders WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if existing:
            result = dict(existing)
            conn.close()
            return result
    conn.close()
    preview = preview_order(payload, source=source)
    instrument = preview.get("instrument")
    order_id = f"ord_{uuid.uuid4().hex[:10]}"
    created_at = _now()
    if not preview["allowed"]:
        primary = preview["errors"][0]
        conn = db.get_db()
        conn.execute(
            """INSERT INTO orders(id,idempotency_key,instrument_id,symbol,side,quantity,status,source,proposal_id,
               rejection_code,rejection_reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (order_id, idempotency_key, instrument["id"] if instrument else payload.get("instrument_id", "unknown"),
             instrument["symbol"] if instrument else payload.get("symbol", "UNKNOWN"), payload.get("side", ""),
             float(payload.get("quantity", payload.get("size", 0)) or 0), "rejected", source, proposal_id,
             primary["code"], primary["message"], created_at),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        conn.close()
        return {**dict(row), "preview": preview}

    position_id = f"p{uuid.uuid4().hex[:8]}"
    conn = db.get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT INTO orders(id,idempotency_key,instrument_id,symbol,side,quantity,status,requested_price,
               fill_price,notional,risk_amount,fee,slippage_bps,stop_loss,take_profit,source,proposal_id,position_id,
               created_at,filled_at) VALUES(?,?,?,?,? ,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (order_id, idempotency_key, instrument["id"], instrument["symbol"], preview["side"], preview["quantity"],
             "filled", preview["quote"]["price"], preview["estimated_fill"], preview["notional"], preview["risk_amount"],
             preview["fee"], preview["slippage_bps"], preview["stop_loss"], preview["take_profit"], source, proposal_id,
             position_id, created_at, created_at),
        )
        protection = "protected" if preview["stop_loss"] is not None else "unprotected"
        conn.execute(
            """INSERT INTO positions(id,pair,asset_class,side,size,entry_price,opened_at,confidence,instrument_id,
               stop_loss,take_profit,protection_status,source,opened_order_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (position_id, instrument["symbol"], instrument["asset_class"], preview["side"], preview["quantity"],
             preview["estimated_fill"], created_at, float(payload.get("confidence", 0.75)), instrument["id"],
             preview["stop_loss"], preview["take_profit"], protection, source, order_id),
        )
        conn.execute(
            "INSERT INTO logs VALUES(?,?,?,?,?,?)",
            (f"l{uuid.uuid4().hex[:8]}", "info", "FILL", instrument["symbol"],
             f"Paper {preview['side']} filled: {preview['quantity']:g} @ {preview['estimated_fill']:.4f}; fee {preview['fee']:.2f}.", created_at),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        return {**dict(row), "preview": preview}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def close_position(position_id: str, *, source: str = "manual_close", reason: str = "manual") -> dict:
    conn = db.get_db()
    row = conn.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone()
    conn.close()
    if not row:
        raise KeyError("position_not_found")
    instrument = _instrument_for_row(row)
    if not instrument:
        raise ValueError("unknown_instrument")
    quote = prices.fetch_quote(instrument.id)
    if not quote or quote["price"] is None or quote["stale"]:
        raise ValueError("quote_unavailable")
    exit_side = "short" if row["side"] == "long" else "long"
    fill, notional, fee = _friction(instrument, exit_side, quote["price"], row["size"])
    gross_pnl = calculate_pnl(instrument, row["side"], row["size"], row["entry_price"], fill)
    conn = db.get_db()
    entry_order = (
        conn.execute("SELECT fee FROM orders WHERE id=?", (row["opened_order_id"],)).fetchone()
        if row["opened_order_id"]
        else None
    )
    conn.close()
    entry_fee = float(entry_order["fee"] or 0) if entry_order else 0.0
    total_fees = entry_fee + fee
    net_pnl = gross_pnl - total_fees
    now = _now()
    order_id = f"ord_{uuid.uuid4().hex[:10]}"
    trade_id = f"t{uuid.uuid4().hex[:8]}"
    conn = db.get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT INTO orders(id,instrument_id,symbol,side,quantity,status,requested_price,fill_price,notional,
               fee,slippage_bps,source,position_id,created_at,filled_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (order_id, instrument.id, instrument.symbol, exit_side, row["size"], "filled", quote["price"], fill,
             notional, fee, SLIPPAGE_BPS[instrument.asset_class], source, position_id, now, now),
        )
        conn.execute(
            """INSERT INTO trades(id,pair,side,size,entry_price,exit_price,pnl,closed_at,instrument_id,fees,exit_reason,source)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (trade_id, instrument.symbol, row["side"], row["size"], row["entry_price"], fill, gross_pnl, now,
             instrument.id, total_fees, reason, source),
        )
        conn.execute("DELETE FROM positions WHERE id=?", (position_id,))
        conn.execute(
            "INSERT INTO logs VALUES(?,?,?,?,?,?)",
            (f"l{uuid.uuid4().hex[:8]}", "info", "EXIT", instrument.symbol,
             f"Paper position closed @ {fill:.4f}; net P&L {net_pnl:+.2f} ({reason}).", now),
        )
        conn.commit()
        return {"order_id": order_id, "trade_id": trade_id, "pnl": net_pnl, "fill_price": fill, "reason": reason}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_protection(position_id: str, stop_loss: float | None, take_profit: float | None) -> dict:
    conn = db.get_db()
    row = conn.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone()
    conn.close()
    if not row:
        raise KeyError("position_not_found")
    instrument = _instrument_for_row(row)
    quote = prices.fetch_quote(instrument.id) if instrument else None
    current = quote["price"] if quote and quote["price"] else row["entry_price"]
    if stop_loss is not None and ((row["side"] == "long" and stop_loss >= current) or (row["side"] == "short" and stop_loss <= current)):
        raise ValueError("invalid_stop")
    if take_profit is not None and ((row["side"] == "long" and take_profit <= current) or (row["side"] == "short" and take_profit >= current)):
        raise ValueError("invalid_target")
    status = "protected" if stop_loss is not None else "unprotected"
    conn = db.get_db()
    conn.execute(
        "UPDATE positions SET stop_loss=?,take_profit=?,protection_status=? WHERE id=?",
        (stop_loss, take_profit, status, position_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone()
    conn.close()
    return dict(updated)


def check_protective_exits() -> list[dict]:
    conn = db.get_db()
    rows = conn.execute("SELECT * FROM positions WHERE stop_loss IS NOT NULL OR take_profit IS NOT NULL").fetchall()
    conn.close()
    exits = []
    for row in rows:
        instrument = _instrument_for_row(row)
        quote = prices.fetch_quote(instrument.id) if instrument else None
        if not quote or quote["price"] is None or quote["stale"]:
            continue
        mark = quote["price"]
        reason = None
        if row["side"] == "long":
            if row["stop_loss"] is not None and mark <= row["stop_loss"]:
                reason = "stop_loss"
            elif row["take_profit"] is not None and mark >= row["take_profit"]:
                reason = "take_profit"
        else:
            if row["stop_loss"] is not None and mark >= row["stop_loss"]:
                reason = "stop_loss"
            elif row["take_profit"] is not None and mark <= row["take_profit"]:
                reason = "take_profit"
        if reason:
            try:
                exits.append(close_position(row["id"], source="protective_exit", reason=reason))
            except (KeyError, ValueError):
                continue
    return exits
