"""Headline archive: RSS feeds, Finnhub (optional key) and Yahoo.

Deduped twice: by URL on insert, then by story. The same story syndicated under slightly
different titles is marked `duplicate_of` the first copy (title word overlap >= 0.8 within
48 hours), so classification and news flow count each story once."""

from __future__ import annotations

import hashlib
import heapq
import math
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


def _prefix(words: frozenset[str], rank: dict[str, int]) -> list[str]:
    """The rarest words of a title, as many as any title it could match must share one of:
    if Jaccard(a, b) >= t, a and b have a common word among the first n - ceil(t*n) + 1 of
    each (words ranked rarest first). One more word than that absorbs float rounding."""
    ordered = sorted(words, key=lambda w: (rank[w], w))
    keep = len(ordered) - math.ceil(DUPLICATE_JACCARD * len(ordered)) + 2
    return ordered[:max(1, keep)]


def _story_matches(rows: list[dict]) -> dict[str, str]:
    """For rows in time order: id -> id of the first earlier original (within the window) that
    tells the same story. Same answer as comparing every pair, but candidates come from an index
    of each original's rarest words (prefix filtering), since the wire calls this after every
    poll that stores something."""
    window = timedelta(hours=DUPLICATE_WINDOW_H)
    titles = [_title_words(row["title"]) for row in rows]
    counts: dict[str, int] = {}
    for words in titles:
        for w in words:
            counts[w] = counts.get(w, 0) + 1
    originals: list[tuple[frozenset[str], str]] = []
    alive: list[bool] = []
    expiry: list[tuple[datetime, int]] = []  # (published, index): drops originals past the window
    by_word: dict[str, list[int]] = {}
    matches: dict[str, str] = {}
    for row, words in zip(rows, titles):
        when = datetime.fromisoformat(row["published_at"].replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        while expiry and when - expiry[0][0] > window:
            alive[heapq.heappop(expiry)[1]] = False
        prefix = _prefix(words, counts) if words else []
        candidates = sorted({i for w in prefix for i in by_word.get(w, ()) if alive[i]})
        match = next((originals[i][1] for i in candidates if is_same_story(words, originals[i][0])), None)
        if match:
            matches[row["id"]] = match
        else:
            index = len(originals)
            originals.append((words, row["id"]))
            alive.append(True)
            heapq.heappush(expiry, (when, index))
            for w in prefix:
                by_word.setdefault(w, []).append(index)
    return matches


def mark_duplicates(days: int = 3) -> int:
    """Mark later copies of a story (near-identical titles within 48h) as duplicates of the first."""
    rows = db.rows("SELECT id, published_at, title, duplicate_of FROM news WHERE published_at >= datetime('now', ?) "
                   "ORDER BY published_at", (f"-{days + 2} days",))
    matches = _story_matches(rows)
    updates = [(match, row["id"]) for row in rows
               if (match := matches.get(row["id"])) and row["duplicate_of"] != match]
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
