"""Headline archive: RSS feeds, Finnhub (optional key) and Yahoo.

Deduped twice: by URL on insert, then by story. The same story syndicated under slightly
different titles is marked `duplicate_of` the first copy (title word overlap >= 0.8 within
48 hours), so classification and news flow count each story once."""

from __future__ import annotations

import hashlib
import html
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

from .. import config, db, live, universe

RSS_FEEDS = {
    "cnbc": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "cnbc-finance": "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "marketwatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "wsj-markets": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "ft-markets": "https://www.ft.com/markets?format=rss",
    "federal-reserve": "https://www.federalreserve.gov/feeds/press_all.xml",
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "oilprice": "https://oilprice.com/rss/main",
    "fxstreet": "https://www.fxstreet.com/rss/news",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (NEXUS research terminal)"}
_TAG = re.compile(r"<[^>]+>")
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset("a an the to of in on for and or as at by is are be with from after amid its it this that says "
                  "new over vs up down".split())
DUPLICATE_JACCARD = 0.8
DUPLICATE_WINDOW_H = 48


def _clean(text: str | None, limit: int = 600) -> str:
    return html.unescape(_TAG.sub(" ", text or "")).strip()[:limit]


def _news_id(url: str | None, title: str) -> str:
    key = (url or "").split("?")[0] or title.lower()
    return "n_" + hashlib.sha1(key.encode()).hexdigest()[:16]


def store_articles(articles: list[dict]) -> int:
    records = []
    for item in articles:
        title = _clean(item.get("title"), 400)
        if not title:
            continue
        tickers = item.get("tickers") or []
        records.append((
            _news_id(item.get("url"), title), item["published_at"], title, _clean(item.get("summary")),
            item.get("url"), item.get("source"), item["provider"], db.dumps(tickers) if tickers else None,
        ))
    before = db.one("SELECT COUNT(*) c FROM news")["c"]
    db.executemany(
        "INSERT OR IGNORE INTO news(id,published_at,title,summary,url,source,provider,tickers) VALUES(?,?,?,?,?,?,?,?)",
        records,
    )
    added = db.one("SELECT COUNT(*) c FROM news")["c"] - before
    if added:
        live.publish("news", added=added)
    return added


def _title_words(title: str) -> frozenset[str]:
    return frozenset(w for w in _WORD.findall(title.lower()) if w not in _STOP and len(w) > 1)


def is_same_story(a: frozenset[str], b: frozenset[str]) -> bool:
    if len(a) < 3 or len(b) < 3:
        return a == b and bool(a)
    return len(a & b) / len(a | b) >= DUPLICATE_JACCARD


def mark_duplicates(days: int = 3) -> int:
    """Mark later copies of a story (near-identical titles within 48h) as duplicates of the first."""
    rows = db.rows("SELECT id, published_at, title, duplicate_of FROM news WHERE published_at >= datetime('now', ?) "
                   "ORDER BY published_at", (f"-{days + 2} days",))
    window = timedelta(hours=DUPLICATE_WINDOW_H)
    originals: list[tuple[datetime, frozenset[str], str]] = []
    updates = []
    for row in rows:
        when = datetime.fromisoformat(row["published_at"].replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        words = _title_words(row["title"])
        originals = [o for o in originals if when - o[0] <= window]
        match = next((o[2] for o in originals if is_same_story(words, o[1])), None)
        if match:
            if row["duplicate_of"] != match:
                updates.append((match, row["id"]))
        else:
            originals.append((when, words, row["id"]))
    db.executemany("UPDATE news SET duplicate_of=? WHERE id=?", updates)
    if updates:
        live.publish("news")
    return len(updates)


def _rss_time(value: str | None) -> str:
    if value:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
        except (TypeError, ValueError):
            pass
    return db.now_iso()


def fetch_rss() -> int:
    stored = 0
    for name, url in RSS_FEEDS.items():
        try:
            response = requests.get(url, timeout=20, headers=HEADERS)
            response.raise_for_status()
            root = ET.fromstring(response.content)
        except Exception as exc:
            db.log("warn", "rss", f"{name}: {exc}")
            continue
        articles = []
        for node in root.iter("item"):
            articles.append({
                "title": node.findtext("title"),
                "summary": node.findtext("description"),
                "url": node.findtext("link"),
                "published_at": _rss_time(node.findtext("pubDate")),
                "source": name,
                "provider": "rss",
            })
        stored += store_articles(articles)
    return stored


def fetch_yahoo(instrument_ids: list[str]) -> int:
    """Yahoo headline RSS per ticker: good ticker tagging, no key needed."""
    items = [item for value in instrument_ids if (item := universe.resolve(value))]
    stored = 0
    for item in items:
        try:
            response = requests.get(
                "https://feeds.finance.yahoo.com/rss/2.0/headline",
                params={"s": item.provider_symbol, "region": "US", "lang": "en-US"}, timeout=20, headers=HEADERS,
            )
            response.raise_for_status()
            root = ET.fromstring(response.content)
        except Exception as exc:
            db.log("warn", "yahoo-rss", f"{item.symbol}: {exc}")
            continue
        stored += store_articles([
            {
                "title": node.findtext("title"), "summary": node.findtext("description"),
                "url": node.findtext("link"), "published_at": _rss_time(node.findtext("pubDate")),
                "source": "yahoo", "provider": "yahoo",
                "tickers": [item.id],
            }
            for node in root.iter("item")
        ])
    return stored


def _finnhub_company(item: universe.Instrument, start: date, end: date, key: str, limit: int = 40) -> int | None:
    """One company-news call. None means rate-limited."""
    try:
        response = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={"symbol": item.symbol.replace("-", "."), "from": start.isoformat(), "to": end.isoformat(),
                    "token": key}, timeout=20,
        )
        if response.status_code == 429:
            return None
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        db.log("warn", "finnhub", f"{item.symbol}: {exc}")
        return 0
    return store_articles([
        {
            "title": row.get("headline"), "summary": row.get("summary"), "url": row.get("url"),
            "source": row.get("source"), "provider": "finnhub", "tickers": [item.id],
            "published_at": datetime.fromtimestamp(row.get("datetime", 0), timezone.utc).isoformat(timespec="seconds"),
        }
        for row in payload[:limit]
    ])


def fetch_finnhub(instrument_ids: list[str], days: int = 7) -> int:
    key = config.secret("finnhub_api_key")
    if not key:
        return 0
    stored = 0
    start, end = date.today() - timedelta(days=days), date.today()
    for value in instrument_ids:
        item = universe.resolve(value)
        if not item or item.asset_class != "stock":
            continue
        count = _finnhub_company(item, start, end, key)
        if count is None:
            break
        stored += count
    try:
        response = requests.get("https://finnhub.io/api/v1/news", params={"category": "general", "token": key}, timeout=20)
        response.raise_for_status()
        stored += store_articles([
            {
                "title": row.get("headline"), "summary": row.get("summary"), "url": row.get("url"),
                "source": row.get("source"), "provider": "finnhub",
                "published_at": datetime.fromtimestamp(row.get("datetime", 0), timezone.utc).isoformat(timespec="seconds"),
            }
            for row in response.json()
        ])
    except Exception as exc:
        db.log("warn", "finnhub", f"general: {exc}")
    return stored


def backfill_finnhub(days: int = 365, progress=None, deadline_s: float = 30 * 60) -> dict:
    """Company news for every stock in the universe, one month per call.
    Finnhub's free tier allows 60 calls a minute and about a year of history."""
    key = config.secret("finnhub_api_key")
    if not key:
        return {"skipped": "no finnhub_api_key"}
    started, stored, calls = time.monotonic(), 0, 0
    months = [(date.today() - timedelta(days=d + 30), date.today() - timedelta(days=d)) for d in range(0, days, 30)]
    for item in (i for i in universe.INSTRUMENTS if i.asset_class == "stock"):
        if progress:
            progress(f"finnhub backfill {item.symbol}")
        for start, end in months:
            if time.monotonic() - started > deadline_s:
                return {"stored": stored, "calls": calls, "stopped": "deadline"}
            count = _finnhub_company(item, start, end, key, limit=250)
            calls += 1
            if count is None:
                time.sleep(30)
                continue
            stored += count
            time.sleep(1.1)
    return {"stored": stored, "calls": calls}


def update_news(focus_ids: list[str] | None = None) -> dict:
    focus_ids = focus_ids or []
    return {
        "rss": fetch_rss(),
        "yahoo": fetch_yahoo(focus_ids) if focus_ids else 0,
        "finnhub": fetch_finnhub(focus_ids),
        "duplicates": mark_duplicates(),
    }
