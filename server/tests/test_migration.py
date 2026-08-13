import sqlite3

import db


LEGACY_SCHEMA = """
CREATE TABLE positions(id TEXT PRIMARY KEY,pair TEXT,asset_class TEXT,side TEXT,size REAL,entry_price REAL,opened_at TEXT,confidence REAL);
CREATE TABLE trades(id TEXT PRIMARY KEY,pair TEXT,side TEXT,size REAL,entry_price REAL,exit_price REAL,pnl REAL,closed_at TEXT);
CREATE TABLE logs(id TEXT PRIMARY KEY,level TEXT,action TEXT,pair TEXT,message TEXT,created_at TEXT);
CREATE TABLE portfolio_config(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE llm_config(id INTEGER PRIMARY KEY,provider TEXT,model TEXT,api_key TEXT,base_url TEXT,num_ctx INTEGER);
CREATE TABLE trade_ideas(id TEXT PRIMARY KEY,symbol TEXT,asset_class TEXT,side TEXT,entry_price REAL,stop_loss REAL,take_profit REAL,confidence REAL,reasoning TEXT,status TEXT,created_at TEXT,closed_at TEXT,outcome_pnl REAL);
CREATE TABLE annotations(id TEXT PRIMARY KEY,symbol TEXT,type TEXT,data TEXT,color TEXT,created_at TEXT);
"""


def test_legacy_migration_backs_up_and_preserves_rows(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    conn.execute("INSERT INTO portfolio_config VALUES('exposure_limit','990')")
    conn.execute(
        "INSERT INTO positions VALUES(?,?,?,?,?,?,?,?)",
        ("p1", "AAPL", "stock", "long", 1, 100, "2026-08-01T00:00:00+00:00", 0.7),
    )
    conn.execute(
        "INSERT INTO trade_ideas VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("i1", "AAPL", "stock", "long", 100, 110, 90, 0.7, "bad geometry", "active", "2026-08-01T00:00:00+00:00", None, None),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(db, "DB_PATH", str(path))
    db.init_db()
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 1
    assert conn.execute("SELECT instrument_id FROM positions").fetchone()[0] == "stock:aapl"
    assert conn.execute("SELECT protection_status FROM positions").fetchone()[0] == "unprotected"
    assert conn.execute("SELECT review_state FROM trade_ideas").fetchone()[0] == "invalid"
    assert conn.execute("SELECT value FROM portfolio_config WHERE key='exposure_limit'").fetchone()[0] == "150"
    backup = conn.execute("SELECT value FROM portfolio_config WHERE key='last_backup_path'").fetchone()[0]
    assert backup and (tmp_path / backup.split("\\")[-1]).exists()
    assert conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == db.SCHEMA_VERSION
    conn.close()

