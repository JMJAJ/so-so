"""Single-password login for a public deployment.

Set NEXUS_PASSWORD to require it; without it (local use) everything stays open. A successful
login sets an HttpOnly cookie holding an expiry and an HMAC of it (keyed by the same secret
that encrypts stored API keys), so no session table is needed. Repeated wrong passwords
from one address are slowed down and then locked out for a while.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time

from . import config

COOKIE = "nexus_session"
SESSION_DAYS = 30
OPEN_PATHS = {"/api/health", "/api/auth/login", "/api/auth/status", "/api/auth/logout"}
MAX_FAILURES = 8
LOCKOUT_SECONDS = 15 * 60
_failures: dict[str, list[float]] = {}


def required() -> bool:
    return bool(os.environ.get("NEXUS_PASSWORD"))


def _sign(payload: str) -> str:
    key = hashlib.sha256(b"session:" + config._key()).digest()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def make_token(now: float | None = None) -> str:
    expires = int((now or time.time()) + SESSION_DAYS * 86400)
    return f"{expires}.{_sign(str(expires))}"


def valid(token: str | None, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    expires, signature = token.split(".", 1)
    if not expires.isdigit() or int(expires) < (now or time.time()):
        return False
    return hmac.compare_digest(signature, _sign(expires))


def locked_out(client: str) -> bool:
    recent = [t for t in _failures.get(client, []) if time.time() - t < LOCKOUT_SECONDS]
    if recent:
        _failures[client] = recent
    else:
        _failures.pop(client, None)  # no empty entry left behind for every client ever seen
    return len(recent) >= MAX_FAILURES


def sweep() -> None:
    """Forget clients whose failed attempts have all aged out."""
    for client in list(_failures):
        locked_out(client)


def check_password(password: str, client: str) -> bool:
    if locked_out(client):
        return False
    ok = hmac.compare_digest(password.encode(), os.environ.get("NEXUS_PASSWORD", "").encode())
    if ok:
        _failures.pop(client, None)
    else:
        _failures.setdefault(client, []).append(time.time())
        time.sleep(1)  # slows guessing
    return ok


def allowed(path: str, token: str | None) -> bool:
    return not required() or not path.startswith("/api") or path in OPEN_PATHS or valid(token)
