"""Headline archive: RSS feeds, Finnhub (optional key) and yfinance, deduped by URL."""

from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

from .. import config, db, universe

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
    return db.one("SELECT COUNT(*) c FROM news")["c"] - before


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


def fetch_finnhub(instrument_ids: list[str], days: int = 7) -> int:
    key = config.secret("finnhub_api_key")
    if not key:
        return 0
    stored = 0
    start, end = (date.today() - timedelta(days=days)).isoformat(), date.today().isoformat()
    for value in instrument_ids:
        item = universe.resolve(value)
        if not item or item.asset_class != "stock":
            continue
        try:
            response = requests.get(
                "https://finnhub.io/api/v1/company-news",
                params={"symbol": item.symbol.replace("-", "."), "from": start, "to": end, "token": key}, timeout=20,
            )
            if response.status_code == 429:
                break
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            db.log("warn", "finnhub", f"{item.symbol}: {exc}")
            continue
        stored += store_articles([
            {
                "title": row.get("headline"), "summary": row.get("summary"), "url": row.get("url"),
                "source": row.get("source"), "provider": "finnhub", "tickers": [item.id],
                "published_at": datetime.fromtimestamp(row.get("datetime", 0), timezone.utc).isoformat(timespec="seconds"),
            }
            for row in payload[:40]
        ])
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


def update_news(focus_ids: list[str] | None = None) -> dict:
    focus_ids = focus_ids or []
    return {
        "rss": fetch_rss(),
        "yahoo": fetch_yahoo(focus_ids) if focus_ids else 0,
        "finnhub": fetch_finnhub(focus_ids),
    }
