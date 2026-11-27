"""Runtime settings (DB-backed with defaults) and encrypted secrets.

Environment variables always win over stored secrets so keys can live in .env.
"""

from __future__ import annotations

import base64
import hashlib
import os
import time

from . import db

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SECRET_PATH = os.path.join(db.DATA_DIR, ".secret")

SECRET_ENV = {
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "openrouter_api_key": "OPENROUTER_API_KEY",
    "nvidia_api_key": "NVIDIA_API_KEY",
    "finnhub_api_key": "FINNHUB_API_KEY",
    "fred_api_key": "FRED_API_KEY",
    # ntfy push notifications: the topic name works like a password (anyone who knows it can read).
    "ntfy_topic": "NTFY_TOPIC",
    "ntfy_token": "NTFY_TOKEN",
}

DEFAULTS: dict[str, str] = {
    "llm_provider": "anthropic",
    "llm_model": "claude-sonnet-5-5",
    "llm_fast_model": "claude-haiku-5-5",
    "llm_base_url": "",
    "autopilot": "true",
    "starting_equity": "100000",
    # Set by a paper-account reset: trades and equity history before it don't count.
    "account_started_at": "",
    "risk_per_trade": "0.01",
    "max_positions": "12",
    "max_exposure": "1.0",
    "max_correlated_risk": "2.0",
    "analyst_shortlist": "12",
    "analyst_max_recs": "5",
    "min_probability": "0.40",
    "enabled_classes": "stock,etf,crypto,forex,commodity",
    "history_years": "10",
    "gdelt_backfill_days": "365",
    "scheduler_enabled": "true",
    # Breaking-news wire (ingest/wire.py): ~50 feeds polled about every minute.
    "wire_enabled": "true",
    # SEC EDGAR asks automated clients to identify themselves with a contact; set yours in Settings.
    "sec_user_agent": "NEXUS research terminal (contact: admin@example.com)",
    # Minutes between the slower news job (Yahoo/Finnhub/GDELT + LLM classification).
    "news_interval_min": "10",
    # Watchlist shared by every device (comma-separated instrument ids); alerts watch it too.
    "watchlist": "etf:spy,etf:qqq,stock:nvda,stock:aapl,crypto:btc,commodity:gold",
    # Push notifications through ntfy (nexus/notify.py). Topic and token are secrets.
    "ntfy_server": "https://ntfy.sh",
    # Breaking news: push alerts at this level or above (3 = top only, 2 = major too, 0 = off).
    # Major (level 2) alerts about a watched, held or AI-called asset are always pushed.
    "notify_news_level": "3",
    # Price moves: push when a watched asset moves this many of its own daily σ (0 = off).
    "notify_move_sigma": "3",
    "notify_calls": "true",
    "notify_exits": "true",
    # A top alert or a big move on a watched asset starts a focused analyst run (at most every 3 h).
    "notify_auto_analyst": "true",
    # Live event trader (agent/trader.py): a focused AI run on one asset when breaking news at
    # this wire level or above tags it, or it moves this many of its own daily σ. Held positions
    # are reviewed on any major alert or 2σ move against them.
    "event_trader": "true",
    "event_trade_level": "3",
    "event_trade_sigma": "2.5",
    "event_trade_max_per_hour": "6",
    # Where tapping a notification opens: the site you use (Vercel URL). Or set NEXUS_PUBLIC_URL.
    "public_url": "",
    # Daily cleanup (nexus/cleanup.py) deletes headlines older than this; 0 keeps every headline.
    # Never below 400: the news page reads up to a year back and the backfill dedupes 400 days.
    "news_retention_days": "730",
}


def _load_dotenv() -> None:
    for path in (os.path.join(ROOT_DIR, ".env"), os.path.join(ROOT_DIR, "server", ".env")):
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


# Settings are read on almost every request; keep them in memory. Writes through this module
# clear the cache at once; SETTINGS_TTL bounds staleness from other processes (the CLI).
SETTINGS_TTL = 30.0
_settings: dict = {"path": None, "at": 0.0, "values": {}}


def _stored() -> dict[str, str]:
    now = time.monotonic()
    if _settings["path"] != db.DB_PATH or now - _settings["at"] > SETTINGS_TTL:
        values = {row["key"]: row["value"] for row in db.rows("SELECT key, value FROM settings")}
        _settings.update(path=db.DB_PATH, at=now, values=values)
    return _settings["values"]


def invalidate_cache() -> None:
    _settings["path"] = None


def get(key: str) -> str:
    stored = _stored()
    if key in stored:
        return stored[key]
    if key in ("llm_model", "llm_fast_model"):
        # Model defaults follow the chosen provider (Claude ids only make sense on Anthropic).
        from .llm import PROVIDERS

        meta = PROVIDERS.get(get("llm_provider"), {})
        if key == "llm_model" and meta.get("default_model"):
            return meta["default_model"]
        if key == "llm_fast_model" and get("llm_provider") != "anthropic":
            return meta.get("fast_model", "")
    if key == "llm_provider" and not os.environ.get("ANTHROPIC_API_KEY") and not _stored_secret("anthropic_api_key"):
        if os.environ.get("OPENAI_API_KEY"):
            return "openai"
        if os.environ.get("OPENROUTER_API_KEY"):
            return "openrouter"
        if os.environ.get("NVIDIA_API_KEY"):
            return "nvidia"
    return DEFAULTS.get(key, "")


def get_float(key: str) -> float:
    try:
        return float(get(key))
    except ValueError:
        return float(DEFAULTS[key])


def get_int(key: str) -> int:
    return int(get_float(key))


def get_bool(key: str) -> bool:
    return get(key).lower() in ("1", "true", "yes", "on")


def set_many(values: dict[str, str]) -> None:
    db.executemany(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        [(key, str(value)) for key, value in values.items() if key in DEFAULTS],
    )
    invalidate_cache()


def all_settings() -> dict[str, str]:
    stored = _stored()
    return {key: stored.get(key, get(key)) for key in DEFAULTS}


# ── Secrets ──────────────────────────────────────────────────────────────────

def _key() -> bytes:
    env = os.environ.get("NEXUS_SECRET")
    if env:
        secret = env
    elif os.path.exists(SECRET_PATH):
        with open(SECRET_PATH, encoding="utf-8") as handle:
            secret = handle.read().strip()
    else:
        secret = base64.urlsafe_b64encode(os.urandom(32)).decode()
        os.makedirs(os.path.dirname(SECRET_PATH), exist_ok=True)
        with open(SECRET_PATH, "w", encoding="utf-8") as handle:
            handle.write(secret)
    return hashlib.sha256(secret.encode()).digest()


def _encrypt(plaintext: str) -> str:
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    iv = os.urandom(16)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(_key()), modes.CBC(iv)).encryptor()
    return base64.urlsafe_b64encode(iv + encryptor.update(padded) + encryptor.finalize()).decode()


def _decrypt(ciphertext: str) -> str:
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    raw = base64.urlsafe_b64decode(ciphertext)
    decryptor = Cipher(algorithms.AES(_key()), modes.CBC(raw[:16])).decryptor()
    padded = decryptor.update(raw[16:]) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode()


def _stored_secret(name: str) -> str:
    value = _stored().get(f"secret:{name}")
    if not value:
        return ""
    try:
        return _decrypt(value)
    except Exception:
        return ""


def secret(name: str) -> str:
    env_name = SECRET_ENV.get(name)
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    return _stored_secret(name)


def set_secret(name: str, value: str) -> None:
    if name not in SECRET_ENV:
        raise ValueError(f"Unknown secret {name}")
    stored = _encrypt(value) if value else ""
    db.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (f"secret:{name}", stored),
    )
    invalidate_cache()


def secret_status() -> dict[str, dict]:
    result = {}
    for name, env_name in SECRET_ENV.items():
        from_env = bool(os.environ.get(env_name))
        value = secret(name)
        result[name] = {
            "set": bool(value),
            "source": "env" if from_env else ("stored" if value else None),
            "hint": f"…{value[-4:]}" if len(value) > 8 else None,
        }
    return result
