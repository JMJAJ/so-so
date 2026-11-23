"""Run the heavy research on GitHub Actions and merge only its results into the live server.

The weekly research job (earnings history, event studies, walk-forward backtest, replay, the
simulation honesty check) needs more memory and time than Render's free instance has. A GitHub
Actions workflow (.github/workflows/research.yml) therefore:
  1. downloads the live server's latest database snapshot as a read-only copy,
  2. runs the `research` job on it (NEXUS_SNAPSHOT_READONLY=1 stops it pushing that copy back),
  3. exports just the tables research writes into a small SQLite "bundle", and uploads it to
     Supabase Storage next to the snapshots, with a tiny JSON manifest.

The live server polls the manifest and, when a newer bundle appears, merges it in one transaction.
Tables that research recomputes from scratch are replaced; earnings events and dates are upserted
(they are append-style and the daily job may have added rows since). Nothing the live server owns
(positions, trades, recommendations, news, settings) is in the bundle, so nothing it recorded
while the workflow ran can be lost.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import sqlite3
import tempfile

import requests

from . import config, db, snapshot

BUNDLE = "research/latest.db.gz"
MANIFEST = "research/latest.json"

# Recomputed in full by the research job: replaced on import.
REPLACE = ("event_impact", "signal_stats", "models", "replay_calls", "sim_checks")
# A bundle without these is broken (empty database, failed run) and must never replace live research.
REQUIRED_NONEMPTY = ("event_impact", "models")

# Append-style: upserted on import. table -> row filter applied on export.
UPSERT = {
    "events": "type IN ('earnings_beat', 'earnings_miss')",
    "upcoming_earnings": "1=1",
}


def export(path: str) -> dict:
    """Write the research tables of the current database into a standalone SQLite file."""
    if os.path.exists(path):
        os.remove(path)
    counts: dict[str, int] = {}
    target = sqlite3.connect(path)
    try:
        target.execute("ATTACH DATABASE ? AS src", (db.DB_PATH,))
        for table in (*REPLACE, *UPSERT):
            where = UPSERT.get(table, "1=1")
            schema = target.execute("SELECT sql FROM src.sqlite_master WHERE type='table' AND name=?",
                                    (table,)).fetchone()
            target.execute(schema[0])  # same definition (keys, WITHOUT ROWID) as the live table
            target.execute(f"INSERT INTO main.{table} SELECT * FROM src.{table} WHERE {where}")
            counts[table] = target.execute(f"SELECT COUNT(*) FROM main.{table}").fetchone()[0]
        target.commit()
        target.execute("DETACH DATABASE src")
    finally:
        target.close()
    return counts


def import_bundle(path: str) -> dict:
    """Merge a bundle into the live database in one transaction. Returns row counts per table."""
    counts: dict[str, int] = {}
    # Own connection: ATTACH is not allowed inside a transaction, and the merge must be one.
    conn = db.connect()
    try:
        conn.execute("ATTACH DATABASE ? AS bundle", (path,))
        present = {row[0] for row in conn.execute("SELECT name FROM bundle.sqlite_master WHERE type='table'")}
        missing = [t for t in (*REPLACE, *UPSERT) if t not in present]
        if missing:
            raise ValueError(f"bundle is missing tables: {', '.join(missing)}")
        empty = [t for t in REQUIRED_NONEMPTY
                 if not conn.execute(f"SELECT COUNT(*) FROM bundle.{t}").fetchone()[0]]
        if empty:
            raise ValueError(f"bundle has no rows in {', '.join(empty)}; keeping the current research")
        conn.execute("BEGIN IMMEDIATE")
        try:
            for table in (*REPLACE, *UPSERT):
                columns = [row[1] for row in conn.execute(f"PRAGMA bundle.table_info({table})")]
                live = {row[1] for row in conn.execute(f"PRAGMA main.table_info({table})")}
                shared = ",".join(c for c in columns if c in live)  # tolerate a newer/older schema
                if table in REPLACE:
                    conn.execute(f"DELETE FROM main.{table}")
                    conn.execute(f"INSERT INTO main.{table}({shared}) SELECT {shared} FROM bundle.{table}")
                else:
                    conn.execute(f"INSERT OR REPLACE INTO main.{table}({shared}) "
                                 f"SELECT {shared} FROM bundle.{table}")
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM bundle.{table}").fetchone()[0]
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        conn.execute("DETACH DATABASE bundle")
    finally:
        conn.close()
    return counts


# ── Supabase Storage transport ───────────────────────────────────────────────

def _storage():
    cfg = snapshot._config()
    if not cfg:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY are not set")
    return cfg[1]


def publish(manifest: dict) -> dict:
    """Export the current database's research tables and upload bundle + manifest."""
    key = _storage()
    with tempfile.TemporaryDirectory() as tmp:
        raw = os.path.join(tmp, "bundle.db")
        counts = export(raw)
        empty = [t for t in REQUIRED_NONEMPTY if not counts.get(t)]
        if empty:
            raise RuntimeError(f"refusing to publish: no rows in {', '.join(empty)} (did the research run?)")
        packed = os.path.join(tmp, "bundle.db.gz")
        with open(raw, "rb") as src, gzip.open(packed, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)
        manifest = {**manifest, "computed_at": db.now_iso(), "tables": counts, "bytes": os.path.getsize(packed)}
        with open(packed, "rb") as body:
            response = requests.post(snapshot._object_url(BUNDLE), data=body, timeout=300,
                                     headers=snapshot._headers(key, **{"x-upsert": "true",
                                                                       "Content-Type": "application/gzip"}))
        response.raise_for_status()
        # Manifest last: the server never sees a manifest for a bundle that isn't uploaded yet.
        response = requests.post(snapshot._object_url(MANIFEST), data=json.dumps(manifest), timeout=60,
                                 headers=snapshot._headers(key, **{"x-upsert": "true",
                                                                   "Content-Type": "application/json"}))
        response.raise_for_status()
    return manifest


def fetch_manifest() -> dict | None:
    key = _storage()
    response = requests.get(snapshot._object_url(MANIFEST), headers=snapshot._headers(key), timeout=30)
    if response.status_code in (400, 404):
        return None
    response.raise_for_status()
    return response.json()


def sync(force: bool = False) -> dict:
    """Import the published bundle if it is newer than the last one imported here."""
    if not snapshot.enabled():
        return {"skipped": "snapshots not configured"}
    manifest = fetch_manifest()
    if not manifest:
        return {"skipped": "no bundle published yet"}
    last = config.get("research_bundle_imported")
    if not force and last and manifest["computed_at"] <= last:
        return {"skipped": "up to date", "computed_at": manifest["computed_at"]}
    key = _storage()
    with tempfile.TemporaryDirectory() as tmp:
        packed = os.path.join(tmp, "bundle.db.gz")
        response = requests.get(snapshot._object_url(BUNDLE), headers=snapshot._headers(key), timeout=300,
                                stream=True)
        response.raise_for_status()
        with open(packed, "wb") as out:
            for chunk in response.iter_content(1 << 20):
                out.write(chunk)
        raw = os.path.join(tmp, "bundle.db")
        with gzip.open(packed, "rb") as src, open(raw, "wb") as dst:
            shutil.copyfileobj(src, dst)
        counts = import_bundle(raw)
    config.set_many({"research_bundle_imported": manifest["computed_at"]})
    _refresh_caches()
    db.log("info", "research", f"imported research bundle from {manifest.get('source', '?')} "
                               f"computed {manifest['computed_at']}")
    return {"imported": counts, "computed_at": manifest["computed_at"], "source": manifest.get("source")}


def _refresh_caches() -> None:
    from . import data
    from .research import scan

    data.invalidate()
    try:
        scan.forecasts(refresh=True)
    except Exception as exc:  # forecasts rebuild on the next request anyway
        db.log("warn", "research", f"forecast refresh after import: {exc}")


def remote_research() -> bool:
    """Research runs on GitHub Actions; the live server only imports it (env NEXUS_RESEARCH_REMOTE=1)."""
    return os.environ.get("NEXUS_RESEARCH_REMOTE", "").lower() in ("1", "true", "yes")
