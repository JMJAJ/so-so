import os
import sys

import numpy as np
import pandas as pd
import pytest

SERVER_DIR = os.path.dirname(os.path.dirname(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from nexus import config, data, db  # noqa: E402
from nexus.ingest import prices  # noqa: E402

SYNTHETIC = {
    "etf:spy": 400.0, "etf:gld": 180.0, "etf:tlt": 100.0, "etf:xlk": 150.0, "etf:xle": 80.0,
    "stock:aapl": 150.0, "stock:msft": 300.0, "stock:jpm": 140.0, "stock:xom": 100.0, "stock:nvda": 200.0,
    "index:vix": 18.0, "index:tnx": 4.0, "index:irx": 3.5, "index:dxy": 100.0,
}


def make_bars(n_days: int = 1400, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize() - pd.Timedelta(days=1), periods=n_days)
    rows = []
    for instrument_id, start in SYNTHETIC.items():
        vol = 0.06 if instrument_id == "index:vix" else 0.012
        path = start * np.exp(np.cumsum(rng.normal(0.0002, vol, n_days)))
        for day, close in zip(dates, path):
            rows.append((instrument_id, day.date().isoformat(), close * 0.998, close * 1.01, close * 0.99, close, 1e6))
    return pd.DataFrame(rows, columns=["instrument_id", "date", "open", "high", "low", "close", "volume"])


def write_bars(frame: pd.DataFrame) -> None:
    db.executemany(
        "INSERT OR REPLACE INTO bars(instrument_id,date,open,high,low,close,volume) VALUES(?,?,?,?,?,?,?)",
        [tuple(row) for row in frame.itertuples(index=False)],
    )
    data.invalidate()


def stub_quote(instrument_id: str) -> dict | None:
    row = db.one("SELECT date, close FROM bars WHERE instrument_id=? ORDER BY date DESC LIMIT 1", (instrument_id,))
    if not row:
        return None
    return {"instrument_id": instrument_id, "price": row["close"], "change_pct": 0.0, "as_of": row["date"],
            "stale": False, "market_open": True}


@pytest.fixture()
def nexus_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "nexus_test.db"))
    monkeypatch.setattr(config, "SECRET_PATH", str(tmp_path / ".secret"))
    db.init_db()
    config.set_many({"scheduler_enabled": "false"})
    data.invalidate()
    monkeypatch.setattr(prices, "quote", stub_quote)
    monkeypatch.setattr(prices, "quotes", lambda ids: {i: stub_quote(i) for i in ids if stub_quote(i)})
    from nexus.research import scan

    scan._cache.update(at=0.0, rows=[])
    yield tmp_path
    data.invalidate()


@pytest.fixture()
def synthetic(nexus_db):
    frame = make_bars()
    write_bars(frame)
    return frame
