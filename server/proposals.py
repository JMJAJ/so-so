"""Validated AI/advisory proposals and approval workflow."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import db
import execution
from instruments import resolve_instrument


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_proposals(status: str | None = None, limit: int = 100) -> list[dict]:
    conn = db.get_db()
    if status:
        rows = conn.execute(
            "SELECT * FROM proposals WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM proposals ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def create_proposal(payload: dict, *, source: str = "ai", auto_execute: bool | None = None) -> dict:
    instrument = resolve_instrument(
        payload.get("instrument_id") or payload.get("symbol", ""), payload.get("asset_class")
    )
    if not instrument:
        raise ValueError("unknown_instrument")
    side = str(payload.get("side", "")).lower()
    if side not in ("long", "short"):
        raise ValueError("invalid_side")
    quantity = payload.get("quantity", payload.get("size"))
    quantity = float(quantity) if quantity not in (None, "") else None
    stop = payload.get("stop_loss")
    target = payload.get("take_profit")
    stop = float(stop) if stop not in (None, "") else None
    target = float(target) if target not in (None, "") else None
    confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.5))))

    conn = db.get_db()
    mode_row = conn.execute("SELECT value FROM portfolio_config WHERE key='agent_mode'").fetchone()
    mode = mode_row["value"] if mode_row else "advisory"
    conn.close()
    proposal_id = f"prop_{uuid.uuid4().hex[:10]}"
    conn = db.get_db()
    conn.execute(
        """INSERT INTO proposals(id,instrument_id,symbol,asset_class,side,quantity,stop_loss,take_profit,
           confidence,rationale,mode,status,source,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            proposal_id, instrument.id, instrument.symbol, instrument.asset_class, side, quantity, stop, target,
            confidence, str(payload.get("rationale") or payload.get("reason") or "No rationale supplied."),
            mode, "pending", source, _now(),
        ),
    )
    conn.commit()
    conn.close()
    should_execute = mode == "guarded_autopilot" if auto_execute is None else auto_execute
    if should_execute:
        return approve_proposal(proposal_id, automatic=True)
    return get_proposal(proposal_id)


def get_proposal(proposal_id: str) -> dict:
    conn = db.get_db()
    row = conn.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
    conn.close()
    if not row:
        raise KeyError("proposal_not_found")
    return dict(row)


def approve_proposal(proposal_id: str, *, automatic: bool = False) -> dict:
    proposal = get_proposal(proposal_id)
    if proposal["status"] != "pending":
        raise ValueError("proposal_not_pending")
    payload = {
        "instrument_id": proposal["instrument_id"], "side": proposal["side"],
        "quantity": proposal["quantity"], "stop_loss": proposal["stop_loss"],
        "take_profit": proposal["take_profit"], "confidence": proposal["confidence"],
        "idempotency_key": f"proposal:{proposal_id}",
    }
    order = execution.execute_order(payload, source="autopilot" if automatic else "proposal", proposal_id=proposal_id)
    status = "executed" if order["status"] == "filled" else "rejected"
    reason = order.get("rejection_reason")
    conn = db.get_db()
    conn.execute(
        "UPDATE proposals SET status=?,rejection_reason=?,decided_at=?,order_id=? WHERE id=?",
        (status, reason, _now(), order["id"], proposal_id),
    )
    conn.commit()
    conn.close()
    return {"proposal": get_proposal(proposal_id), "order": order}


def reject_proposal(proposal_id: str, reason: str = "Rejected by operator") -> dict:
    proposal = get_proposal(proposal_id)
    if proposal["status"] != "pending":
        raise ValueError("proposal_not_pending")
    conn = db.get_db()
    conn.execute(
        "UPDATE proposals SET status='rejected',rejection_reason=?,decided_at=? WHERE id=?",
        (reason, _now(), proposal_id),
    )
    conn.commit()
    conn.close()
    return get_proposal(proposal_id)

