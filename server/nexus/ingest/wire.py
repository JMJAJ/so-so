"""Breaking-news wire: many sources polled about once a minute, with alerts.

The slower `news` job (RSS, Yahoo, Finnhub, GDELT, then LLM classification) runs every few
minutes. This module is the fast path: it polls ~50 feeds concurrently with conditional GETs
(ETag / Last-Modified, so an unchanged feed costs one tiny request), tags headlines with the
instruments they name, and raises an alert for fresh high-impact stories (CEO changes, M&A,
guidance, regulators, wars, central banks).

Sources: newswires (via Google News, which aggregates thousands of outlets), global outlets,
the press-release services where companies publish first (PR Newswire, GlobeNewswire,
Business Wire), SEC EDGAR 8-K filings (Item 5.02 is an officer change), and central banks.

Honest limits: free feeds trail professional terminals (Bloomberg, Reuters, Dow Jones
newswires) by seconds to minutes. An alert tells you something happened and how far the
price has already moved; it is not evidence that the move will continue."""

from __future__ import annotations

import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

from .. import config, db, live, universe
from . import news

GN = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="
GN_TOPIC = "https://news.google.com/rss/headlines/section/topic/{}?hl=en-US&gl=US&ceid=US:en"


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    group: str
    every: int = 60  # seconds between polls


FEEDS: list[Feed] = [
    # Newswires and big outlets without public RSS, through Google News (published within the hour).
    Feed("reuters", GN + quote_plus("site:reuters.com when:1h"), "wire"),
    Feed("ap", GN + quote_plus("site:apnews.com when:1h"), "wire"),
    Feed("bloomberg-gn", GN + quote_plus("site:bloomberg.com when:1h"), "wire"),
    Feed("barrons", GN + quote_plus("site:barrons.com when:1h"), "wire", 120),
    # Dow Jones' public RSS stopped updating in 2025; WSJ and MarketWatch come through Google News.
    Feed("wsj", GN + quote_plus("site:wsj.com when:1h"), "wire"),
    Feed("marketwatch", GN + quote_plus("site:marketwatch.com when:1h"), "wire"),
    Feed("guardian", GN + quote_plus("site:theguardian.com business when:1h"), "wire", 180),
    Feed("globenewswire", GN + quote_plus("site:globenewswire.com when:1h"), "press", 120),
    Feed("gn-business", GN_TOPIC.format("BUSINESS"), "aggregator"),
    Feed("gn-world", GN_TOPIC.format("WORLD"), "aggregator"),
    Feed("gn-tech", GN_TOPIC.format("TECHNOLOGY"), "aggregator", 120),
    Feed("gn-breaking-corp", GN + quote_plus(
        '("CEO" OR "chief executive" OR "steps down" OR "resigns" OR "acquire" OR "merger" OR "guidance") when:1h'),
        "aggregator"),
    Feed("gn-breaking-macro", GN + quote_plus(
        '("Federal Reserve" OR "rate cut" OR "rate hike" OR tariffs OR sanctions OR OPEC OR ceasefire) when:1h'),
        "aggregator"),
    # Direct outlet feeds.
    Feed("bloomberg", "https://feeds.bloomberg.com/markets/news.rss", "outlet"),
    Feed("cnbc-top", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "outlet"),
    Feed("cnbc-world", "https://www.cnbc.com/id/100727362/device/rss/rss.html", "outlet"),
    Feed("cnbc-tech", "https://www.cnbc.com/id/19854910/device/rss/rss.html", "outlet"),
    Feed("cnbc-earnings", "https://www.cnbc.com/id/15839135/device/rss/rss.html", "outlet"),
    Feed("ft", "https://www.ft.com/rss/home", "outlet"),
    Feed("seekingalpha", "https://seekingalpha.com/market_currents.xml", "outlet"),
    Feed("benzinga", "https://www.benzinga.com/feed", "outlet"),
    Feed("investing", "https://www.investing.com/rss/news_25.rss", "outlet"),
    Feed("nyt-business", "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "outlet"),
    Feed("nyt-world", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "outlet", 120),
    Feed("bbc-business", "https://feeds.bbci.co.uk/news/business/rss.xml", "outlet"),
    Feed("bbc-world", "https://feeds.bbci.co.uk/news/world/rss.xml", "outlet", 120),
    Feed("aljazeera", "https://www.aljazeera.com/xml/rss/all.xml", "outlet", 120),
    Feed("dw-business", "https://rss.dw.com/rdf/rss-en-bus", "outlet", 120),
    Feed("france24-business", "https://www.france24.com/en/business/rss", "outlet", 180),
    Feed("nikkei-asia", "https://asia.nikkei.com/rss/feed/nar", "outlet", 120),
    Feed("scmp-business", "https://www.scmp.com/rss/92/feed", "outlet", 120),
    Feed("et-markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "outlet", 120),
    Feed("fortune", "https://fortune.com/feed/", "outlet", 180),
    Feed("business-insider", "https://feeds.businessinsider.com/custom/all", "outlet", 120),
    Feed("axios", "https://api.axios.com/feed/", "outlet", 120),
    Feed("techcrunch", "https://techcrunch.com/feed/", "outlet", 180),
    Feed("theverge", "https://www.theverge.com/rss/index.xml", "outlet", 180),
    Feed("zerohedge", "https://feeds.feedburner.com/zerohedge/feed", "outlet"),
    Feed("oilprice", "https://oilprice.com/rss/main", "outlet", 120),
    Feed("fxstreet", "https://www.fxstreet.com/rss/news", "outlet"),
    Feed("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", "outlet"),
    Feed("cointelegraph", "https://cointelegraph.com/rss", "outlet"),
    Feed("decrypt", "https://decrypt.co/feed", "outlet", 120),
    # Where companies announce first.
    Feed("prnewswire", "https://www.prnewswire.com/rss/news-releases-list.rss", "press"),
    Feed("businesswire", "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtRWA==", "press"),
    # Regulators and central banks.
    Feed("sec-8k", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb=&owner=include"
                   "&count=100&output=atom", "filing"),
    Feed("sec-press", "https://www.sec.gov/news/pressreleases.rss", "regulator", 300),
    Feed("federal-reserve", "https://www.federalreserve.gov/feeds/press_all.xml", "central-bank"),
    Feed("ecb", "https://www.ecb.europa.eu/rss/press.html", "central-bank", 120),
    Feed("boe", "https://www.bankofengland.co.uk/rss/news", "central-bank", 300),
]

FOCUS_EVERY = 180   # per-asset Google News queries for held / open-call / top-ranked assets
FOCUS_LIMIT = 25
FRESH_MINUTES = 45  # only stories this recent can raise an alert (the first poll sees old items)
WORKERS = 16
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


# ── Instrument tagging ───────────────────────────────────────────────────────

# Names and people that identify an instrument besides its universe name (case-sensitive).
EXTRA_ALIASES: dict[str, list[str]] = {
    "stock:nvda": ["Nvidia", "Jensen Huang"], "stock:aapl": ["Tim Cook"], "stock:msft": ["Satya Nadella"],
    "stock:googl": ["Google", "Sundar Pichai", "YouTube", "Waymo"], "stock:meta": ["Facebook", "Instagram",
    "Zuckerberg"], "stock:amzn": ["AWS", "Andy Jassy"], "stock:tsla": ["Elon Musk"], "stock:amd": ["Lisa Su"],
    "stock:intc": ["Lip-Bu Tan"], "stock:jpm": ["JP Morgan", "Jamie Dimon"], "stock:xom": ["Exxon", "ExxonMobil"],
    "stock:ge": ["General Electric"], "stock:c": ["Citi", "Citibank"], "stock:t": ["AT&T"],
    "stock:brk-b": ["Berkshire", "Warren Buffett", "Greg Abel"], "stock:bkng": ["Booking Holdings"],
    "stock:avgo": ["Hock Tan"], "stock:lly": ["Lilly"], "stock:jnj": ["J&J"], "stock:pg": ["P&G"],
    "stock:ko": ["Coca Cola"], "stock:dis": ["Walt Disney"], "stock:wmt": ["Wal-Mart"], "stock:pltr": ["Alex Karp"],
    "stock:ba": ["Boeing"], "stock:coin": ["Brian Armstrong"], "stock:v": ["Visa Inc"],
    "crypto:btc": ["BTC"], "crypto:eth": ["Ether", "ETH"],
    "commodity:wti": ["crude oil", "Crude oil", "oil prices", "Oil prices", "OPEC"],
    "commodity:brent": ["Brent"], "commodity:gold": ["gold prices", "Gold prices", "gold price", "Gold price"],
    "commodity:natgas": ["natural gas", "Natural gas", "LNG"], "commodity:copper": ["copper", "Copper"],
    "commodity:wheat": ["wheat", "Wheat"], "commodity:corn": ["corn", "Corn"],
    "index:spx": ["S&P 500"], "index:ndx": ["Nasdaq"], "index:tnx": ["Treasury yields"],
    "forex:usdjpy": ["yen", "Bank of Japan", "BOJ"], "forex:eurusd": ["euro", "ECB", "Lagarde"],
    "forex:gbpusd": ["sterling", "Bank of England"], "forex:usdcny": ["yuan", "PBOC"],
}
# Universe names too generic to match on their own.
SKIP_NAMES = {"stock:v", "stock:meta", "stock:t", "stock:c", "stock:ge", "stock:ups", "stock:rtx", "stock:bkng"}
_aliases: list[tuple[re.Pattern, str]] | None = None


def _alias_patterns() -> list[tuple[re.Pattern, str]]:
    global _aliases
    if _aliases is None:
        out: list[tuple[re.Pattern, str]] = []
        for item in universe.INSTRUMENTS:
            names = list(EXTRA_ALIASES.get(item.id, []))
            if item.asset_class in ("stock", "crypto") and item.id not in SKIP_NAMES:
                names.append(item.name)
                if item.name.isupper() and len(item.name) > 3:
                    names.append(item.name.title())  # NVIDIA -> Nvidia
            if item.id == "stock:meta":
                names.append("Meta Platforms")
            if item.id in ("stock:ups", "stock:rtx"):
                names.append(item.name)  # all-caps, matched case-sensitively below
            for name in names:
                out.append((re.compile(rf"(?<![\w$]){re.escape(name)}(?!\w)"), item.id))
            if item.asset_class == "stock":
                # Ticker forms used by press releases and traders: $NVDA, (NASDAQ: NVDA), NYSE:XOM.
                symbol = re.escape(item.symbol.replace("-", "."))
                out.append((re.compile(rf"\${symbol}\b|\b(?:NASDAQ|NYSE|Nasdaq|Nyse)\s*:\s*{symbol}\b"), item.id))
        _aliases = out
    return _aliases


def tag_instruments(text: str) -> list[str]:
    return sorted({iid for pattern, iid in _alias_patterns() if pattern.search(text)})


# ── Alert detection ──────────────────────────────────────────────────────────

# (kind, pattern). Corporate kinds need a tagged instrument; macro kinds stand alone.
CORPORATE_RULES = [
    ("leadership", r"\b(CEO|chief executive|chairman|CFO)\b.*\b(resign|step(s|ping)? down|ousted|fired|depart|"
                   r"retire|appoint|name[sd]?|return|reinstat|replace|successor|exit)|\b(resign|steps down|ousted|"
                   r"returns as|reinstated as|named|appointed)\b.*\b(CEO|chief executive|chairman)\b|Item 5\.02"),
    ("deal", r"\b(acquire[sd]?|acquisition|merger|merge|buyout|takeover|to buy|agrees to buy|tender offer|"
             r"spin[- ]?off|stake in)\b"),
    ("guidance", r"\b(guidance|outlook|forecast|profit warning|warns|beats|misses|tops estimates|"
                 r"record revenue|quarterly results)\b"),
    ("regulatory", r"\b(SEC|DOJ|FTC|antitrust|probe|investigation|lawsuit|sued|fine[ds]?|subpoena|indict|"
                   r"export (ban|curbs|controls)|FDA (approv|reject)|recall)\b"),
    ("capital", r"\b(buyback|repurchase|dividend (cut|suspend|hike)|stock split|offering|bankrupt|chapter 11|"
                r"default|delist|halt(ed)?|downgrade|upgrade|price target)\b"),
    ("shock", r"\b(plunge[sd]?|soar(s|ed)?|surge[sd]?|crash(es|ed)?|tumble[sd]?|skyrocket|halted)\b"),
]
MACRO_RULES = [
    ("central-bank", r"\b(Fed|FOMC|Federal Reserve|ECB|Bank of Japan|BOJ|Bank of England|PBOC)\b.*\b(cut|hike|raise[sd]?|"
                     r"hold[s]?|emergency|surprise|pause)"),
    ("geopolitics", r"\b(invasion|invade[sd]?|airstrikes?|missile strikes?|declares? war|ceasefire|coup|"
                    r"blockade|martial law|nuclear test)\b"),
    ("geo-watch", r"\b(war|attack|missiles?|nuclear|troops)\b"),
    ("trade", r"\b(tariff[s]?|export ban|trade deal|trade war|embargo)\b"),
    ("sanctions", r"\b(sanction[s]?)\b"),
    ("macro-data", r"\b(CPI|inflation|jobs report|payrolls|unemployment rate|GDP|recession)\b.*\b(surprise|"
                   r"unexpected|jump|plunge|hotter|cooler|beat|miss)"),
    ("energy", r"\b(OPEC\+?|oil output|production cut|pipeline (attack|shut))\b"),
]
_CORP = [(k, re.compile(p, re.I)) for k, p in CORPORATE_RULES]
_MACRO = [(k, re.compile(p)) for k, p in MACRO_RULES]  # case-sensitive: "Fed", not "fed up"
LEVEL = {"leadership": 3, "deal": 3, "regulatory": 2, "capital": 2, "guidance": 2, "shock": 2,
         "central-bank": 3, "geopolitics": 2, "geo-watch": 1, "trade": 2, "sanctions": 1, "macro-data": 2, "energy": 2}


def detect_alert(title: str, summary: str, tickers: list[str]) -> dict | None:
    """Kind and level (1-3) of a headline worth interrupting for, or None."""
    text = f"{title}. {summary[:300]}"
    kinds = []
    if tickers:
        kinds += [k for k, p in _CORP if p.search(text)]
    kinds += [k for k, p in _MACRO if p.search(text)]
    if not kinds:
        return None
    return {"kinds": kinds, "level": max(LEVEL[k] for k in kinds)}


# ── Fetching and parsing ─────────────────────────────────────────────────────

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _time(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_feed(content: bytes, source: str, google: bool = False) -> list[dict]:
    """RSS 2.0, RDF/RSS 1.0 and Atom items as article dicts."""
    root = ET.fromstring(content)
    out = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        fields: dict[str, str] = {}
        link = None
        for child in node:
            name = _local(child.tag)
            if name == "link":
                link = link or child.get("href") or (child.text or "").strip() or None
            elif child.text and name not in fields:
                fields[name] = child.text
        title = news._clean(fields.get("title"), 400)
        outlet = fields.get("source")
        from_google = google or "news.google.com" in (link or "")
        if outlet and from_google:
            title = re.sub(rf"\s+-\s+{re.escape(outlet.strip())}\s*$", "", title)  # "Headline - Reuters"
        published = _time(fields.get("pubDate") or fields.get("published") or fields.get("updated")
                          or fields.get("date"))
        out.append({
            "title": title,
            "summary": fields.get("description") or fields.get("summary") or fields.get("content") or "",
            "url": link or fields.get("guid"),
            "published_at": published,
            "source": outlet.strip() if outlet and from_google else source,
            "provider": "wire",
        })
    return out


_state: dict[str, dict] = {}  # per feed: etag, modified, next poll, failures, last result
_state_lock = threading.Lock()


def _fetch(feed: Feed) -> tuple[Feed, list[dict] | None, str | None]:
    """(feed, articles or None if unchanged/failed, error)."""
    st = _state.setdefault(feed.name, {})
    headers = {"User-Agent": config.get("sec_user_agent") if feed.group == "filing" else BROWSER_UA,
               "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}
    if st.get("etag"):
        headers["If-None-Match"] = st["etag"]
    if st.get("modified"):
        headers["If-Modified-Since"] = st["modified"]
    try:
        response = requests.get(feed.url, headers=headers, timeout=12)
        if response.status_code == 304:
            return feed, None, None
        response.raise_for_status()
        articles = parse_feed(response.content, feed.name, google="news.google.com" in feed.url)
    except Exception as exc:
        return feed, None, f"{type(exc).__name__}: {str(exc)[:160]}"
    st["etag"] = response.headers.get("ETag")
    st["modified"] = response.headers.get("Last-Modified")
    return feed, articles, None


def _focus_feeds(focus_ids: list[str]) -> list[Feed]:
    out = []
    for iid in focus_ids[:FOCUS_LIMIT]:
        item = universe.get(iid)
        if not item or item.asset_class == "index":
            continue
        query = f'"{item.name}"' + (f" OR {item.symbol}" if item.asset_class == "stock" and len(item.symbol) > 2 else "")
        out.append(Feed(f"focus-{item.symbol.lower()}", GN + quote_plus(f"({query}) when:1h"), "focus", FOCUS_EVERY))
    return out


def _due(feed: Feed, now: float) -> bool:
    return _state.get(feed.name, {}).get("next", 0.0) <= now


def _schedule(feed: Feed, now: float, error: str | None) -> None:
    st = _state.setdefault(feed.name, {})
    if error:
        st["failures"] = st.get("failures", 0) + 1
        st["next"] = now + min(feed.every * 2 ** st["failures"], 3600)  # back off up to an hour
        if st["failures"] in (1, 5):
            db.log("warn", "wire", f"{feed.name}: {error}")
    else:
        st["failures"] = 0
        st["next"] = now + feed.every
    st["error"] = error
    st["last"] = db.now_iso()


def _store(articles: list[dict], fetched_at: str) -> list[dict]:
    """Insert new articles; return the ones that were not already stored."""
    now = datetime.now(timezone.utc)
    ready = []
    for article in articles:
        if not article.get("title"):
            continue
        published = article.get("published_at")
        # Missing or future timestamps (feeds lie) are clamped to the time we saw it.
        if not published or published > fetched_at:
            published = fetched_at
        elif published < (now - timedelta(days=7)).isoformat():
            continue
        article["published_at"] = published
        text = f"{article['title']} {news._clean(article.get('summary'), 400)}"
        article["tickers"] = tag_instruments(text)
        article["_id"] = news._news_id(article.get("url"), news._clean(article["title"], 400))
        ready.append(article)
    if not ready:
        return []
    ids = list({a["_id"] for a in ready})
    existing: set[str] = set()
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        existing |= {r["id"] for r in db.rows(f"SELECT id FROM news WHERE id IN ({','.join('?' * len(chunk))})",
                                              chunk)}
    fresh, seen = [], set()
    for article in ready:
        if article["_id"] in existing or article["_id"] in seen:
            continue
        seen.add(article["_id"])
        fresh.append(article)
    if fresh:
        news.store_articles(fresh)
        db.executemany("UPDATE news SET fetched_at=? WHERE id=? AND fetched_at IS NULL",
                       [(fetched_at, a["_id"]) for a in fresh])
    return fresh


def _raise_alerts(fresh: list[dict], fetched_at: str) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=FRESH_MINUTES)).isoformat(timespec="seconds")
    alerts = []
    for article in fresh:
        if article["published_at"] < cutoff:
            continue
        found = detect_alert(article["title"], news._clean(article.get("summary"), 400), article["tickers"])
        if not found:
            continue
        alerts.append({"id": article["_id"], "title": article["title"], "source": article.get("source"),
                       "url": article.get("url"), "published_at": article["published_at"], "fetched_at": fetched_at,
                       "tickers": article["tickers"], **found})
    if not alerts:
        return []
    # One story arrives from dozens of outlets for hours. The first headline per story fires;
    # later ones are stored as follow-ups of it and do not interrupt again.
    stories = _open_stories()
    unique: list[dict] = []
    follow_ups: list[tuple[str, str]] = []
    for alert in sorted(alerts, key=lambda a: a["published_at"]):
        key = story_key(alert)
        original = next((s for s in stories + unique if _same(key, story_key(s))), None)
        if original:
            follow_ups.append((db.dumps({"kinds": alert["kinds"], "level": alert["level"],
                                         "follow_up_of": original["id"]}), alert["id"]))
            continue
        unique.append(alert)
    _attach_moves(unique)
    db.executemany("UPDATE news SET alert=? WHERE id=?",
                   [(db.dumps({k: a[k] for k in ("kinds", "level", "moves")}), a["id"]) for a in unique] + follow_ups)
    for alert in unique:
        live.publish("alert", alert=alert)
    return unique


STORY_HOURS = 12
_PRIMARY_KIND_ORDER = list(LEVEL)


def story_key(alert: dict) -> tuple:
    """(instruments, main kind) for company/asset news; title words for untagged macro news."""
    kinds = sorted(alert["kinds"], key=lambda k: (-LEVEL[k], _PRIMARY_KIND_ORDER.index(k)))
    tradable = [t for t in alert["tickers"] if not t.startswith("index:")]
    if tradable:
        return ("asset", frozenset(tradable), kinds[0])
    return ("words", news._title_words(alert["title"]), kinds[0])


def _same(a: tuple, b: tuple) -> bool:
    if a[0] != b[0] or a[2] != b[2]:
        return False
    if a[0] == "asset":
        return bool(a[1] & b[1])
    return news.is_same_story(a[1], b[1])


def _open_stories() -> list[dict]:
    """Alerts that fired in the last STORY_HOURS (follow-ups excluded)."""
    since = (datetime.now(timezone.utc) - timedelta(hours=STORY_HOURS)).isoformat(timespec="seconds")
    out = []
    for row in db.rows("SELECT id, title, tickers, alert FROM news WHERE alert IS NOT NULL AND published_at >= ?",
                       (since,)):
        alert = db.loads(row["alert"], {}) or {}
        if alert.get("follow_up_of") or not alert.get("kinds"):
            continue
        out.append({"id": row["id"], "title": row["title"], "tickers": db.loads(row["tickers"], []) or [],
                    "kinds": alert["kinds"]})
    return out


def _attach_moves(alerts: list[dict]) -> None:
    """How far each tagged asset has already moved today, so the alert shows what is priced in."""
    from . import prices

    ids = sorted({t for a in alerts for t in a["tickers"]})[:12]
    try:
        quotes = prices.quotes(ids) if ids else {}
    except Exception:
        quotes = {}
    for alert in alerts:
        alert["moves"] = {t: {"price": q.get("price"), "change_pct": q.get("change_pct")}
                          for t in alert["tickers"] if (q := quotes.get(t))}


def poll(focus_ids: list[str] | None = None, force: bool = False) -> dict:
    """Fetch every feed that is due; store new headlines; raise alerts for fresh high-impact ones."""
    if not _state_lock.acquire(blocking=False):
        return {"skipped": "already polling"}
    try:
        started = time.monotonic()
        now = time.time()
        feeds = [f for f in FEEDS + _focus_feeds(focus_ids or []) if force or _due(f, now)]
        if not feeds:
            return {"feeds": 0, "new": 0, "alerts": 0}
        fetched_at = db.now_iso()
        fresh: list[dict] = []
        failed = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for feed, articles, error in pool.map(_fetch, feeds):
                _schedule(feed, now, error)
                failed += bool(error)
                if articles:
                    new = _store(articles, fetched_at)
                    _state[feed.name]["new"] = len(new)
                    fresh += new
        alerts = _raise_alerts(fresh, fetched_at)
        if fresh:
            news.mark_duplicates(days=1)
        return {"feeds": len(feeds), "failed": failed, "new": len(fresh), "alerts": len(alerts),
                "seconds": round(time.monotonic() - started, 1)}
    finally:
        _state_lock.release()


def sources() -> list[dict]:
    """Every feed with its last poll, error and backoff state (for the UI)."""
    out = []
    for feed in FEEDS:
        st = _state.get(feed.name, {})
        out.append({"name": feed.name, "group": feed.group, "every": feed.every, "last": st.get("last"),
                    "error": st.get("error"), "failures": st.get("failures", 0), "new": st.get("new")})
    return out


def recent_alerts(minutes: int = 24 * 60, min_level: int = 1, limit: int = 100) -> list[dict]:
    rows = db.rows(
        """SELECT id, published_at, fetched_at, title, url, source, tickers, alert, category, direction, magnitude
           FROM news WHERE alert IS NOT NULL AND published_at >= ? ORDER BY published_at DESC LIMIT ?""",
        ((datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds"), min(limit * 20, 4000)),
    )
    out, follow_ups = [], {}
    for row in rows:
        alert = db.loads(row.pop("alert"), {}) or {}
        if alert.get("follow_up_of"):
            follow_ups[alert["follow_up_of"]] = follow_ups.get(alert["follow_up_of"], 0) + 1
            continue
        if alert.get("level", 0) < min_level:
            continue
        row["tickers"] = db.loads(row.get("tickers"), []) or []
        out.append({**row, **alert})
    for row in out:
        row["follow_ups"] = follow_ups.get(row["id"], 0)  # other outlets carrying the same story
    return out[:limit]


# ── Background loop ──────────────────────────────────────────────────────────

_thread: threading.Thread | None = None
_stop = threading.Event()
LOOP_SECONDS = 30  # each feed still waits its own `every`; this is just how often we check


def start(focus: callable) -> None:
    """Poll forever on a daemon thread. `focus()` returns the instruments to watch closely."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()

    def run() -> None:
        while not _stop.is_set():
            if config.get_bool("wire_enabled"):
                try:
                    poll(focus())
                except Exception as exc:  # one bad poll must not kill the loop
                    db.log("warn", "wire", f"poll: {exc}")
            _stop.wait(LOOP_SECONDS)

    _thread = threading.Thread(target=run, daemon=True, name="news-wire")
    _thread.start()


def stop() -> None:
    _stop.set()
