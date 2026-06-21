import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "nexus.db")


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=1000")  # Auto-checkpoint every 1000 pages
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = get_db()
    db.executescript("""
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
        
        -- Performance indexes
        CREATE INDEX IF NOT EXISTS idx_trade_ideas_symbol ON trade_ideas(symbol);
        CREATE INDEX IF NOT EXISTS idx_trade_ideas_status ON trade_ideas(status);
        CREATE INDEX IF NOT EXISTS idx_annotations_symbol ON annotations(symbol);
        CREATE INDEX IF NOT EXISTS idx_logs_created_at ON logs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_positions_pair ON positions(pair);
        CREATE INDEX IF NOT EXISTS idx_trades_closed_at ON trades(closed_at DESC);
    """)
    db.execute("INSERT OR IGNORE INTO portfolio_config VALUES ('starting_equity', '100000')")
    db.execute("INSERT OR IGNORE INTO portfolio_config VALUES ('display_currency', 'USD')")
    db.execute("INSERT OR IGNORE INTO portfolio_config VALUES ('risk_profile', 'moderate')")
    db.execute("INSERT OR IGNORE INTO portfolio_config VALUES ('allowed_asset_classes', 'forex,stock,crypto,cfd,futures')")
    db.execute("INSERT OR IGNORE INTO portfolio_config VALUES ('exposure_limit', '80')")
    db.execute("INSERT OR IGNORE INTO llm_config (id, provider, model, api_key, base_url) VALUES (1, 'ollama', 'minimax-m3:cloud', '', '')")
    db.commit()
    db.close()
