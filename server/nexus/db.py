"""SQLite storage for NEXUS v3.

One file, WAL mode, short-lived connections. Every table that holds history is
keyed by date so ingestion is idempotent (INSERT OR REPLACE / ON CONFLICT).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

DATA_DIR = os.environ.get("NEXUS_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))
DB_PATH = os.environ.get("NEXUS_DB_PATH", os.path.join(DATA_DIR, "nexus_v3.db"))
SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    instrument_id TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL NOT NULL, volume REAL,
    PRIMARY KEY (instrument_id, date)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS macro_series (
    series_id TEXT NOT NULL,
    date TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (series_id, date)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS theme_series (
    theme TEXT NOT NULL,
    date TEXT NOT NULL,
    count REAL NOT NULL,
    tone REAL,
    goldstein REAL,
    PRIMARY KEY (theme, date)
) WITHOUT ROWID;

-- Structured, dated events with long history (earnings, rate moves, macro
-- surprises, market shocks, geopolitical spikes). Event studies run on these.
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    instrument_id TEXT,
    scope TEXT NOT NULL,
    date TEXT NOT NULL,
    magnitude REAL,
    surprise REAL,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    approx_date INTEGER NOT NULL DEFAULT 0,
    meta TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_type_date ON events(type, date);
CREATE INDEX IF NOT EXISTS idx_events_instrument ON events(instrument_id, date);
CREATE INDEX IF NOT EXISTS idx_events_date ON events(date DESC);

-- Headline archive. Grows over time; classified by the LLM into the event taxonomy.
CREATE TABLE IF NOT EXISTS news (
    id TEXT PRIMARY KEY,
    published_at TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT,
    source TEXT,
    provider TEXT NOT NULL,
    tickers TEXT,
    category TEXT,
    direction INTEGER,
    magnitude INTEGER,
    affected TEXT,
    rationale TEXT,
    tone REAL,
    classified_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_news_published ON news(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_category ON news(category, published_at DESC);

CREATE TABLE IF NOT EXISTS event_impact (
    type TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    n INTEGER NOT NULL,
    mean REAL, median REAL, baseline REAL, edge REAL,
    hit_rate REAL, t_stat REAL, p_value REAL,
    q_value REAL, edge_early REAL, edge_late REAL, stable INTEGER, reliable INTEGER,
    measure TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (type, instrument_id, horizon)
) WITHOUT ROWID;

-- Next scheduled earnings report per stock (for "is there earnings inside the holding period?").
CREATE TABLE IF NOT EXISTS upcoming_earnings (
    instrument_id TEXT PRIMARY KEY,
    date TEXT,
    updated_at TEXT NOT NULL
);

-- Point-in-time replay of the evidence policy: what its calls would have done.
CREATE TABLE IF NOT EXISTS replay_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    event_type TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    probability REAL NOT NULL,
    base REAL,
    realized_return REAL NOT NULL,
    win INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS signal_stats (
    signal TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    n INTEGER NOT NULL,
    ic REAL, hit_rate REAL, mean_excess REAL, long_short REAL, t_stat REAL,
    period_start TEXT, period_end TEXT,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (signal, asset_class, horizon)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS models (
    asset_class TEXT PRIMARY KEY,
    horizon INTEGER NOT NULL,
    payload TEXT NOT NULL,
    computed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    stop REAL NOT NULL,
    target REAL NOT NULL,
    expected_return REAL,
    probability REAL NOT NULL,
    confidence TEXT NOT NULL,
    thesis TEXT NOT NULL,
    catalysts TEXT,
    evidence TEXT,
    invalidation TEXT,
    signal_snapshot TEXT,
    source TEXT NOT NULL,
    run_id TEXT,
    status TEXT NOT NULL,
    position_id TEXT,
    expires_at TEXT NOT NULL,
    closed_at TEXT,
    exit_price REAL,
    exit_reason TEXT,
    realized_return REAL,
    benchmark_return REAL,
    excess_return REAL,
    mark_price REAL,
    mark_return REAL,
    marked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_recs_status ON recommendations(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_recs_instrument ON recommendations(instrument_id);

CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    status TEXT NOT NULL,
    entry_price REAL,
    entry_fee REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    opened_at TEXT,
    stop REAL,
    target REAL,
    expires_at TEXT,
    recommendation_id TEXT,
    source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    position_id TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT NOT NULL,
    gross_pnl REAL NOT NULL,
    fees REAL NOT NULL,
    net_pnl REAL NOT NULL,
    exit_reason TEXT NOT NULL,
    recommendation_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_closed ON trades(closed_at DESC);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    account_id TEXT NOT NULL DEFAULT 'main',
    date TEXT NOT NULL,
    equity REAL NOT NULL,
    cash REAL NOT NULL,
    exposure REAL NOT NULL,
    spy_close REAL,
    PRIMARY KEY (account_id, date)
) WITHOUT ROWID;

-- Paper trading accounts. AI recommendations are shared research; positions, trades and
-- equity history belong to one account.
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    starting_equity REAL NOT NULL,
    started_at TEXT NOT NULL DEFAULT '',
    gate TEXT NOT NULL DEFAULT 'strict',
    autopilot INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

-- Simulation honesty check: the simulator run on past dates (data <= date only), with the
-- final-day band it gave and what actually happened (research/simulate.py).
CREATE TABLE IF NOT EXISTS sim_checks (
    instrument_id TEXT NOT NULL,
    date TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    p10 REAL, p25 REAL, p50 REAL, p75 REAL, p90 REAL,
    p_up REAL,
    realized REAL NOT NULL,
    PRIMARY KEY (instrument_id, date, horizon)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    name TEXT PRIMARY KEY,
    last_started TEXT,
    last_finished TEXT,
    last_status TEXT,
    last_error TEXT,
    last_summary TEXT,
    duration_ms INTEGER
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    summary TEXT,
    transcript TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    level TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_created ON logs(created_at DESC);

-- Push notifications (nexus/notify.py). `key` makes each event notify once.
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    priority INTEGER NOT NULL,
    click TEXT,
    status TEXT NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at DESC);

-- Derived results worth keeping across restarts (e.g. the forecast scan); always recomputable.
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    at REAL NOT NULL,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA synchronous=NORMAL")
    # A checkpointed WAL is truncated back to this size instead of keeping its high-water mark.
    conn.execute("PRAGMA journal_size_limit=67108864")
    return conn


# One connection per thread (and database path), reused across queries: opening a connection
# and setting its pragmas costs more than most queries here, especially on a slow host.
_local = threading.local()
_all: list[sqlite3.Connection] = []
_all_lock = threading.Lock()


def _thread_connection() -> tuple[sqlite3.Connection, dict]:
    pool = getattr(_local, "pool", None)
    if pool is None:
        pool = _local.pool = {}
    entry = pool.get(DB_PATH)
    if entry is None:
        conn = connect()
        entry = pool[DB_PATH] = (conn, {"depth": 0})
        with _all_lock:
            _all.append(conn)
    return entry


def close_all() -> None:
    """Close every pooled connection (before replacing the database file, and in tests)."""
    with _all_lock:
        connections = list(_all)
        _all.clear()
    for conn in connections:
        try:
            conn.close()
        except sqlite3.Error:
            pass
    _local.pool = {}


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    """A transaction on this thread's connection. Nested sessions join the outer one, which
    commits (or rolls back) once at the end."""
    conn, state = _thread_connection()
    state["depth"] += 1
    try:
        yield conn
        if state["depth"] == 1:
            conn.commit()
    except Exception:
        if state["depth"] == 1:
            conn.rollback()
        raise
    finally:
        state["depth"] -= 1


# Columns added after a table first shipped: (table, column definition).
COLUMN_MIGRATIONS = [
    ("event_impact", "q_value REAL"), ("event_impact", "edge_early REAL"), ("event_impact", "edge_late REAL"),
    ("event_impact", "stable INTEGER"), ("event_impact", "reliable INTEGER"),
    ("news", "duplicate_of TEXT"),
    # Breaking-news wire: when we first saw the headline, and its alert (JSON kinds/level/moves).
    ("news", "fetched_at TEXT"), ("news", "alert TEXT"),
    ("recommendations", "stated_probability REAL"), ("recommendations", "fact_check TEXT"),
    ("recommendations", "base_probability REAL"), ("replay_calls", "base REAL"),
    # Skills the AI had loaded when it made the call / closed it early, as JSON ["name@version"].
    ("recommendations", "skills TEXT"), ("recommendations", "close_skills TEXT"),
    # AI early close: what holding to stop/target/horizon would have returned instead.
    ("recommendations", "hold_return REAL"),
    # Post-mortem lesson written after the call closed.
    ("recommendations", "lesson TEXT"),
    # Sizing tier the server gave the call (core / tactical / base_rate / override) and the
    # fraction of the normal risk budget its paper positions use.
    ("recommendations", "size_tier TEXT"), ("recommendations", "risk_mult REAL"),
    # Paper accounts (existing rows belong to the default account).
    ("positions", "account_id TEXT NOT NULL DEFAULT 'main'"),
    ("trades", "account_id TEXT NOT NULL DEFAULT 'main'"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, definition in COLUMN_MIGRATIONS:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if definition.split()[0] not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
    # equity_snapshots was keyed by date alone; rebuild it keyed by (account, date).
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(equity_snapshots)")}
    if "account_id" not in columns:
        conn.executescript("""
            ALTER TABLE equity_snapshots RENAME TO equity_snapshots_old;
            CREATE TABLE equity_snapshots (
                account_id TEXT NOT NULL DEFAULT 'main', date TEXT NOT NULL, equity REAL NOT NULL,
                cash REAL NOT NULL, exposure REAL NOT NULL, spy_close REAL, PRIMARY KEY (account_id, date)
            ) WITHOUT ROWID;
            INSERT INTO equity_snapshots(account_id,date,equity,cash,exposure,spy_close)
                SELECT 'main', date, equity, cash, exposure, spy_close FROM equity_snapshots_old;
            DROP TABLE equity_snapshots_old;
        """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_account ON positions(account_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_account ON trades(account_id, closed_at)")


def init_db() -> None:
    with session() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_meta(version, applied_at) VALUES(?, ?)",
            (SCHEMA_VERSION, now_iso()),
        )


def rows(sql: str, params: tuple | list = ()) -> list[dict]:
    with session() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def one(sql: str, params: tuple | list = ()) -> dict | None:
    with session() as conn:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None


def execute(sql: str, params: tuple | list = ()) -> None:
    with session() as conn:
        conn.execute(sql, params)


def executemany(sql: str, params: list[tuple]) -> None:
    if not params:
        return
    with session() as conn:
        conn.executemany(sql, params)


def log(level: str, kind: str, message: str) -> None:
    try:
        execute("INSERT INTO logs(created_at, level, kind, message) VALUES(?,?,?,?)", (now_iso(), level, kind, message[:2000]))
    except sqlite3.Error:
        return
    from . import live

    live.publish("logs")


def dumps(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"))


def loads(value: str | bytes | None, default: Any = None) -> Any:
    """JSON from a column; also reads zlib-compressed JSON (old run transcripts, see cleanup.py)."""
    if not value:
        return default
    try:
        if isinstance(value, (bytes, bytearray, memoryview)):
            value = zlib.decompress(bytes(value)).decode("utf-8")
        return json.loads(value)
    except (TypeError, ValueError, zlib.error):
        return default
