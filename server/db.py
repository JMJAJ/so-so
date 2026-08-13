"""SQLite lifecycle, backups, and forward-only schema migrations."""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime, timezone


DB_PATH = os.environ.get("NEXUS_DB_PATH", os.path.join(os.path.dirname(__file__), "data", "nexus.db"))
SCHEMA_VERSION = 2
_last_backup_path: str | None = None


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=1000")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _has_table(conn, table):
        return set()
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
    name = definition.split()[0]
    if name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _backup_if_needed(conn: sqlite3.Connection) -> str | None:
    global _last_backup_path
    if not os.path.exists(DB_PATH) or not _has_table(conn, "positions"):
        return None
    current = 0
    if _has_table(conn, "schema_migrations"):
        row = conn.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
        current = int(row["version"] or 0)
    if current >= SCHEMA_VERSION:
        row = conn.execute("SELECT value FROM portfolio_config WHERE key='last_backup_path'").fetchone()
        _last_backup_path = row["value"] if row else None
        return _last_backup_path
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root, ext = os.path.splitext(DB_PATH)
    backup_path = f"{root}.pre-v{SCHEMA_VERSION}-{stamp}{ext or '.db'}"
    conn.execute("PRAGMA wal_checkpoint(FULL)")
    shutil.copy2(DB_PATH, backup_path)
    _last_backup_path = backup_path
    return backup_path


def _create_base_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS positions (
            id TEXT PRIMARY KEY,
            pair TEXT NOT NULL,
            asset_class TEXT NOT NULL,
            side TEXT NOT NULL,
            size REAL NOT NULL,
            entry_price REAL NOT NULL,
            opened_at TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.7
        );
        CREATE TABLE IF NOT EXISTS trades (
            id TEXT PRIMARY KEY,
            pair TEXT NOT NULL,
            side TEXT NOT NULL,
            size REAL NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL NOT NULL,
            pnl REAL NOT NULL,
            closed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS logs (
            id TEXT PRIMARY KEY,
            level TEXT NOT NULL,
            action TEXT NOT NULL,
            pair TEXT,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS portfolio_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS llm_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            provider TEXT NOT NULL DEFAULT 'ollama',
            model TEXT NOT NULL DEFAULT 'minimax-m3:cloud',
            api_key TEXT NOT NULL DEFAULT '',
            base_url TEXT NOT NULL DEFAULT '',
            num_ctx INTEGER NOT NULL DEFAULT 8192
        );
        CREATE TABLE IF NOT EXISTS trade_ideas (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            asset_class TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss REAL,
            take_profit REAL,
            confidence REAL,
            reasoning TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            closed_at TEXT,
            outcome_pnl REAL
        );
        CREATE TABLE IF NOT EXISTS annotations (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            type TEXT NOT NULL,
            data TEXT NOT NULL,
            color TEXT,
            created_at TEXT NOT NULL
        );
        """
    )


def _create_v2_schema(conn: sqlite3.Connection) -> None:
    for definition in (
        "instrument_id TEXT", "stop_loss REAL", "take_profit REAL",
        "protection_status TEXT NOT NULL DEFAULT 'unprotected'",
        "source TEXT NOT NULL DEFAULT 'legacy'", "opened_order_id TEXT",
    ):
        _add_column(conn, "positions", definition)
    for definition in (
        "instrument_id TEXT", "fees REAL NOT NULL DEFAULT 0",
        "exit_reason TEXT NOT NULL DEFAULT 'legacy'", "source TEXT NOT NULL DEFAULT 'legacy'",
    ):
        _add_column(conn, "trades", definition)
    _add_column(conn, "trade_ideas", "instrument_id TEXT")
    _add_column(conn, "trade_ideas", "review_state TEXT NOT NULL DEFAULT 'valid'")

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            idempotency_key TEXT UNIQUE,
            instrument_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            status TEXT NOT NULL,
            requested_price REAL,
            fill_price REAL,
            notional REAL NOT NULL DEFAULT 0,
            risk_amount REAL,
            fee REAL NOT NULL DEFAULT 0,
            slippage_bps REAL NOT NULL DEFAULT 0,
            stop_loss REAL,
            take_profit REAL,
            source TEXT NOT NULL,
            proposal_id TEXT,
            position_id TEXT,
            rejection_code TEXT,
            rejection_reason TEXT,
            created_at TEXT NOT NULL,
            filled_at TEXT
        );
        CREATE TABLE IF NOT EXISTS proposals (
            id TEXT PRIMARY KEY,
            instrument_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            asset_class TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL,
            stop_loss REAL,
            take_profit REAL,
            confidence REAL,
            rationale TEXT,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            rejection_reason TEXT,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            decided_at TEXT,
            order_id TEXT
        );
        CREATE TABLE IF NOT EXISTS agent_runs (
            id TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            duration_ms INTEGER,
            error TEXT,
            proposal_count INTEGER NOT NULL DEFAULT 0,
            executed_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS equity_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL,
            equity REAL NOT NULL,
            realized REAL NOT NULL,
            unrealized REAL NOT NULL,
            cash REAL NOT NULL,
            gross_exposure REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_orders_instrument ON orders(instrument_id);
        CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_agent_runs_started ON agent_runs(started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_equity_snapshots_time ON equity_snapshots(captured_at DESC);
        CREATE INDEX IF NOT EXISTS idx_trade_ideas_symbol ON trade_ideas(symbol);
        CREATE INDEX IF NOT EXISTS idx_trade_ideas_status ON trade_ideas(status);
        CREATE INDEX IF NOT EXISTS idx_annotations_symbol ON annotations(symbol);
        CREATE INDEX IF NOT EXISTS idx_logs_created_at ON logs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_positions_pair ON positions(pair);
        CREATE INDEX IF NOT EXISTS idx_trades_closed_at ON trades(closed_at DESC);
        """
    )


def _repair_legacy_data(conn: sqlite3.Connection, backup_path: str | None) -> None:
    from instruments import resolve_instrument

    for table, symbol_column in (("positions", "pair"), ("trades", "pair"), ("trade_ideas", "symbol")):
        rows = conn.execute(
            f"SELECT id, {symbol_column} AS symbol, asset_class FROM {table} WHERE instrument_id IS NULL"
            if table != "trades"
            else f"SELECT id, {symbol_column} AS symbol, NULL AS asset_class FROM {table} WHERE instrument_id IS NULL"
        ).fetchall()
        for row in rows:
            instrument = resolve_instrument(row["symbol"], row["asset_class"])
            if instrument:
                conn.execute(f"UPDATE {table} SET instrument_id=? WHERE id=?", (instrument.id, row["id"]))

    conn.execute(
        "UPDATE positions SET protection_status=CASE WHEN stop_loss IS NULL THEN 'unprotected' ELSE 'protected' END"
    )
    ideas = conn.execute("SELECT * FROM trade_ideas").fetchall()
    now = datetime.now(timezone.utc)
    for idea in ideas:
        review = "valid"
        if idea["status"] == "closed":
            review = "scored" if idea["outcome_pnl"] is not None else "unscored"
        else:
            side = idea["side"]
            entry, stop, target = idea["entry_price"], idea["stop_loss"], idea["take_profit"]
            invalid = side not in ("long", "short")
            if stop is not None and target is not None:
                invalid = invalid or (side == "long" and not (stop < entry < target))
                invalid = invalid or (side == "short" and not (target < entry < stop))
            if invalid:
                review = "invalid"
            else:
                try:
                    created = datetime.fromisoformat(idea["created_at"].replace("Z", "+00:00"))
                    if (now - created).days >= 7:
                        review = "stale"
                except (TypeError, ValueError):
                    review = "needs_review"
        conn.execute("UPDATE trade_ideas SET review_state=? WHERE id=?", (review, idea["id"]))

    exposure = conn.execute("SELECT value FROM portfolio_config WHERE key='exposure_limit'").fetchone()
    if exposure and float(exposure["value"]) > 150:
        conn.execute("UPDATE portfolio_config SET value='150' WHERE key='exposure_limit'")
        conn.execute(
            "INSERT INTO logs VALUES (?,?,?,?,?,?)",
            (
                f"migration_v{SCHEMA_VERSION}", "warn", "MIGRATION", None,
                f"Legacy exposure limit {exposure['value']}% was capped at the guarded maximum of 150%.",
                now.isoformat(),
            ),
        )
    if backup_path:
        conn.execute(
            "INSERT INTO portfolio_config(key,value) VALUES('last_backup_path',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (backup_path,),
        )


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    try:
        _create_base_schema(conn)
        backup_path = _backup_if_needed(conn)
        _create_v2_schema(conn)
        _repair_legacy_data(conn, backup_path)
        defaults = {
            "starting_equity": "100000", "display_currency": "USD",
            "risk_profile": "balanced", "allowed_asset_classes": "forex,stock,crypto,cfd,futures",
            "exposure_limit": "80", "agent_mode": "advisory", "kill_switch": "false",
        }
        for key, value in defaults.items():
            conn.execute("INSERT OR IGNORE INTO portfolio_config VALUES (?,?)", (key, value))
        conn.execute(
            "INSERT OR IGNORE INTO llm_config (id, provider, model, api_key, base_url) VALUES (1, 'ollama', 'minimax-m3:cloud', '', '')"
        )
        conn.execute(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) VALUES (?,?)",
            (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def last_backup_path() -> str | None:
    return _last_backup_path
