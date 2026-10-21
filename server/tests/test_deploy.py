"""Deployment pieces: login gate and database snapshots (Supabase Storage mocked)."""

import io

import pytest
from fastapi.testclient import TestClient

from nexus import auth, db, jobs, snapshot


@pytest.fixture()
def client(nexus_db, monkeypatch):
    monkeypatch.setattr(jobs, "run_async", lambda name: None)
    from nexus.api import app

    with TestClient(app) as test_client:
        yield test_client


def test_open_without_password(client, monkeypatch):
    monkeypatch.delenv("NEXUS_PASSWORD", raising=False)
    assert client.get("/api/portfolio").status_code == 200
    assert client.get("/api/auth/status").json() == {"required": False, "authenticated": False}


def test_password_gate(client, monkeypatch):
    monkeypatch.setenv("NEXUS_PASSWORD", "correct horse")
    monkeypatch.setattr(auth.time, "sleep", lambda s: None)
    assert client.get("/api/portfolio").status_code == 401
    assert client.get("/api/health").json()["ok"] is True
    assert client.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    response = client.post("/api/auth/login", json={"password": "correct horse"})
    assert response.status_code == 200 and auth.COOKIE in response.cookies
    assert client.get("/api/portfolio").status_code == 200
    assert client.get("/api/auth/status").json()["authenticated"] is True
    client.post("/api/auth/logout")
    client.cookies.clear()
    assert client.get("/api/portfolio").status_code == 401


def test_tokens_expire_and_cannot_be_forged(nexus_db):
    token = auth.make_token(now=1_000)
    assert auth.valid(token, now=2_000)
    assert not auth.valid(token, now=1_000 + auth.SESSION_DAYS * 86400 + 1)
    expires, _ = token.split(".")
    assert not auth.valid(f"{int(expires) + 99}.{token.split('.')[1]}", now=2_000)


def test_lockout_after_repeated_failures(monkeypatch):
    monkeypatch.setenv("NEXUS_PASSWORD", "pw")
    monkeypatch.setattr(auth.time, "sleep", lambda s: None)
    auth._failures.clear()
    for _ in range(auth.MAX_FAILURES):
        auth.check_password("wrong", "1.2.3.4")
    assert auth.locked_out("1.2.3.4") and not auth.check_password("pw", "1.2.3.4")
    assert auth.check_password("pw", "5.6.7.8")


class FakeStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.beats: list = []
        self.missing_table = False

    def post(self, url, data=None, headers=None, json=None, timeout=None):
        if "/rest/v1/" in url:
            self.beats.append((url, json, headers["Prefer"]))
            return _Response(404 if self.missing_table else 201)
        if "/object/list/" in url:
            return _Response(200, json_body=[{"name": n.split("/")[-1]} for n in self.objects if "/daily/" in n])
        self.objects[url] = data.read()
        assert headers["x-upsert"] == "true"
        return _Response(200)

    def get(self, url, headers=None, timeout=None, stream=False):
        if url not in self.objects:
            return _Response(400)
        return _Response(200, content=self.objects[url])

    def delete(self, url, headers=None, json=None, timeout=None):
        return _Response(200)


class _Response:
    def __init__(self, status, content=b"", json_body=None):
        self.status_code, self._content, self._json = status, content, json_body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise snapshot.requests.HTTPError(str(self.status_code))

    def iter_content(self, size):
        stream = io.BytesIO(self._content)
        while chunk := stream.read(size):
            yield chunk

    def json(self):
        return self._json


def test_snapshot_round_trip(nexus_db, monkeypatch):
    storage = FakeStorage()
    for name in ("post", "get", "delete"):
        monkeypatch.setattr(snapshot.requests, name, getattr(storage, name))
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
    db.log("info", "test", "remember me")
    result = snapshot.push("test")
    assert result["pushed"] and any(k.endswith("/nexus/nexus_v3.db.gz") for k in storage.objects)
    assert any("/nexus/daily/" in k for k in storage.objects)
    assert snapshot.push_if_changed("again") is None  # unchanged database: no upload
    assert not snapshot.pull()  # a local database exists: never overwritten without force
    db.execute("DELETE FROM logs")
    assert snapshot.pull(force=True)
    assert db.one("SELECT COUNT(*) c FROM logs WHERE message='remember me'")["c"] == 1


def test_heartbeat_upserts_one_row_and_survives_missing_table(nexus_db, monkeypatch):
    storage = FakeStorage()
    monkeypatch.setattr(snapshot.requests, "post", storage.post)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
    monkeypatch.setattr(snapshot, "_last_beat", 0.0)
    assert snapshot.heartbeat()
    url, body, prefer = storage.beats[0]
    assert url.endswith("/rest/v1/nexus_heartbeat") and body["id"] == 1 and "merge-duplicates" in prefer
    assert not snapshot.heartbeat()  # throttled: at most every HEARTBEAT_HOURS
    storage.missing_table = True
    assert not snapshot.heartbeat(force=True)
    assert snapshot.status()["heartbeat_error"]


def test_snapshot_disabled_without_credentials(nexus_db, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert not snapshot.enabled() and snapshot.push("x")["pushed"] is False
