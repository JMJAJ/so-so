import os

import pytest

from nexus import db, research_bundle, snapshot


def _seed_research(tag: str) -> None:
    db.execute("DELETE FROM event_impact")
    db.execute("DELETE FROM models")
    db.execute(
        "INSERT INTO event_impact(type,instrument_id,horizon,n,measure,computed_at) VALUES(?,?,?,?,?,?)",
        (f"fed_cut_{tag}", "etf:spy", 20, 12, "abnormal", db.now_iso()),
    )
    db.execute("INSERT INTO models(asset_class,horizon,payload,computed_at) VALUES(?,?,?,?)",
               ("stock", 20, f'{{"tag": "{tag}"}}', db.now_iso()))


def _event(event_id: str, kind: str, title: str) -> None:
    db.execute("INSERT OR REPLACE INTO events(id,type,instrument_id,scope,date,title,source) VALUES(?,?,?,?,?,?,?)",
               (event_id, kind, "stock:aapl", "asset", "2026-11-01", title, "test"))


def test_bundle_round_trip_keeps_live_state(nexus_db, monkeypatch, tmp_path):
    # "GitHub Actions" database: fresh research plus a new earnings event.
    actions_db = str(tmp_path / "actions.db")
    monkeypatch.setattr(db, "DB_PATH", actions_db)
    db.init_db()
    _seed_research("new")
    _event("e_new", "earnings_beat", "Apple beats")
    _event("e_fed", "fed_decision", "Fed holds")  # not research-owned: must not travel
    bundle = str(tmp_path / "bundle.db")
    counts = research_bundle.export(bundle)
    assert counts["event_impact"] == 1 and counts["events"] == 1
    db.close_all()

    # Live database: stale research, an earnings event, and state only the live server owns.
    live_db = str(tmp_path / "live.db")
    monkeypatch.setattr(db, "DB_PATH", live_db)
    db.init_db()
    _seed_research("old")
    _event("e_old", "earnings_miss", "Apple missed")
    db.execute("INSERT INTO logs(level,kind,message,created_at) VALUES('info','test','keep me',?)", (db.now_iso(),))

    research_bundle.import_bundle(bundle)

    assert [r["type"] for r in db.rows("SELECT type FROM event_impact")] == ["fed_cut_new"]  # replaced
    assert "new" in db.one("SELECT payload FROM models")["payload"]
    ids = {r["id"] for r in db.rows("SELECT id FROM events")}
    assert ids == {"e_old", "e_new"}  # upserted, nothing deleted, fed event not imported
    assert db.one("SELECT COUNT(*) c FROM logs WHERE message='keep me'")["c"] == 1


def test_empty_bundle_is_refused(nexus_db, tmp_path):
    _seed_research("live")
    db.execute("DELETE FROM models")
    bundle = str(tmp_path / "empty.db")
    research_bundle.export(bundle)
    _seed_research("live")
    with pytest.raises(ValueError, match="no rows"):
        research_bundle.import_bundle(bundle)
    assert db.one("SELECT COUNT(*) c FROM models")["c"] == 1  # untouched


def test_read_only_copy_never_pushes(nexus_db, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test")
    monkeypatch.setenv("NEXUS_SNAPSHOT_READONLY", "1")
    called = []
    monkeypatch.setattr(snapshot.requests, "post", lambda *a, **k: called.append(a))
    assert snapshot.push("test")["pushed"] is False
    assert not called and os.path.exists(db.DB_PATH)
