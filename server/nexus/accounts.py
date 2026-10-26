"""Paper trading accounts.

Each account has its own starting money, positions, trades, equity history and reset date.
AI recommendations are shared research: any account can trade a call, and the analyst's
autopilot opens it in every account that has autopilot on.

`gate` decides what an account accepts from propose_recommendation:
  strict  only calls with positive expected value and probability >= min_probability
  any     whatever the user asks for; the computed probability and EV are still recorded

The account a request acts on comes from the X-Nexus-Account header (set by the UI) and lives
in a context variable, so code deep in the call stack doesn't need it passed down.
"""

from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from . import config, db

DEFAULT_ID = "main"
GATES = ("strict", "any")
_current: ContextVar[str] = ContextVar("nexus_account", default=DEFAULT_ID)


def ensure_default() -> None:
    """Create the default account from the pre-accounts settings (starting money, last reset)."""
    if db.one("SELECT 1 FROM accounts WHERE id=?", (DEFAULT_ID,)):
        return
    db.execute(
        "INSERT INTO accounts(id,name,starting_equity,started_at,gate,autopilot,created_at) VALUES(?,?,?,?,?,?,?)",
        (DEFAULT_ID, "Main", config.get_float("starting_equity"), config.get("account_started_at"), "strict",
         int(config.get_bool("autopilot")), db.now_iso()),
    )


def all_accounts() -> list[dict]:
    ensure_default()
    return [_public(row) for row in db.rows("SELECT * FROM accounts ORDER BY created_at")]


def get(account_id: str | None = None) -> dict:
    ensure_default()
    row = db.one("SELECT * FROM accounts WHERE id=?", (account_id or current(),))
    if not row:
        raise KeyError(f"Account not found: {account_id}")
    return _public(row)


def _public(row: dict) -> dict:
    return {**row, "autopilot": bool(row["autopilot"])}


def _validate_money(value) -> float:
    try:
        amount = float(str(value).replace(",", "").replace("$", ""))
    except ValueError:
        raise ValueError("Starting money must be a number") from None
    if not 100 <= amount <= 1_000_000_000:
        raise ValueError("Starting money must be between $100 and $1,000,000,000")
    return amount


def create(name: str, starting_equity, gate: str = "strict", autopilot: bool = False) -> dict:
    name = name.strip()[:40]
    if not name:
        raise ValueError("Give the account a name")
    if gate not in GATES:
        raise ValueError(f"gate must be one of {', '.join(GATES)}")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:20] or "account"
    account_id = f"{slug}-{uuid.uuid4().hex[:4]}"
    db.execute(
        "INSERT INTO accounts(id,name,starting_equity,started_at,gate,autopilot,created_at) VALUES(?,?,?,?,?,?,?)",
        (account_id, name, _validate_money(starting_equity), db.now_iso(), gate, int(autopilot), db.now_iso()),
    )
    return get(account_id)


def update(account_id: str, **fields) -> dict:
    current_row = get(account_id)
    changes: dict = {}
    if fields.get("name") is not None:
        changes["name"] = str(fields["name"]).strip()[:40] or current_row["name"]
    if fields.get("starting_equity") is not None:
        changes["starting_equity"] = _validate_money(fields["starting_equity"])
    if fields.get("gate") is not None:
        if fields["gate"] not in GATES:
            raise ValueError(f"gate must be one of {', '.join(GATES)}")
        changes["gate"] = fields["gate"]
    if fields.get("autopilot") is not None:
        changes["autopilot"] = int(bool(fields["autopilot"]))
    if changes:
        assignments = ", ".join(f"{key}=?" for key in changes)
        db.execute(f"UPDATE accounts SET {assignments} WHERE id=?", (*changes.values(), account_id))
    return get(account_id)


def mark_reset(account_id: str, starting_equity=None) -> None:
    values: list = [db.now_iso()]
    sql = "UPDATE accounts SET started_at=?"
    if starting_equity is not None:
        sql += ", starting_equity=?"
        values.append(_validate_money(starting_equity))
    db.execute(sql + " WHERE id=?", (*values, account_id))


def delete(account_id: str) -> None:
    if account_id == DEFAULT_ID:
        raise ValueError("The Main account can't be deleted")
    get(account_id)
    with db.session() as conn:
        conn.execute("DELETE FROM positions WHERE account_id=?", (account_id,))
        conn.execute("DELETE FROM trades WHERE account_id=?", (account_id,))
        conn.execute("DELETE FROM equity_snapshots WHERE account_id=?", (account_id,))
        conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))


def current() -> str:
    return _current.get()


def resolve(account_id: str | None) -> str:
    """A requested account id if it exists, else the default (stale ids from old browsers)."""
    if account_id and db.one("SELECT 1 FROM accounts WHERE id=?", (account_id,)):
        return account_id
    return DEFAULT_ID


def set_current(account_id: str):
    return _current.set(account_id)


@contextmanager
def use(account_id: str) -> Iterator[None]:
    token = _current.set(account_id)
    try:
        yield
    finally:
        _current.reset(token)
