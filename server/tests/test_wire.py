from datetime import datetime, timedelta, timezone

from nexus import db, live
from nexus.ingest import wire


def _rss(items: list[tuple[str, str, datetime]], gn: bool = False) -> bytes:
    body = "".join(
        f"<item><title>{t}</title><link>{u}</link><pubDate>{d.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>"
        + ("<source url='https://reuters.com'>Reuters</source>" if gn else "") + "</item>"
        for t, u, d in items
    )
    return f"<?xml version='1.0'?><rss><channel>{body}</channel></rss>".encode()


def test_parse_rss_atom_rdf():
    now = datetime.now(timezone.utc)
    rss = wire.parse_feed(_rss([("Nvidia rallies - Reuters", "https://x/1", now)], gn=True), "gn-business", google=True)
    assert rss[0]["title"] == "Nvidia rallies" and rss[0]["source"] == "Reuters"
    atom = wire.parse_feed(b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>8-K - NVIDIA CORP</title>
        <link href="https://sec.gov/a"/><updated>2026-11-23T14:00:00-05:00</updated>
        <summary>Item 5.02 Departure of Directors or Certain Officers</summary></entry></feed>""", "sec-8k")
    assert atom[0]["url"] == "https://sec.gov/a" and atom[0]["published_at"] == "2026-11-23T19:00:00+00:00"
    rdf = wire.parse_feed(b"""<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/"><item><title>Euro slips</title>
        <link>https://dw/1</link><dc:date>2026-11-23T10:00:00Z</dc:date></item></rdf:RDF>""", "dw-business")
    assert rdf[0]["title"] == "Euro slips" and rdf[0]["published_at"].startswith("2026-11-23T10:00")


def test_tagging_is_specific():
    assert wire.tag_instruments("Jensen Huang returns as Nvidia CEO") == ["stock:nvda"]
    assert "stock:nvda" in wire.tag_instruments("Chipmaker (NASDAQ: NVDA) announces")
    assert wire.tag_instruments("New visa rules for students; meta-analysis of intelligence") == []
    assert "stock:intc" not in wire.tag_instruments("Artificial intelligence boom")


def test_detect_alert():
    hit = wire.detect_alert("Nvidia CEO Jensen Huang steps down", "", ["stock:nvda"])
    assert hit and "leadership" in hit["kinds"] and hit["level"] == 3
    assert wire.detect_alert("Nvidia unveils a new gaming card", "", ["stock:nvda"]) is None
    # Corporate patterns need a tagged instrument; macro ones don't.
    assert wire.detect_alert("Startup CEO steps down", "", []) is None
    assert wire.detect_alert("Federal Reserve announces surprise rate cut", "", [])["level"] == 3
    assert wire.detect_alert("Fans are fed up with the cut", "", []) is None
    assert wire.detect_alert("10% electricity rate hike coming for homes", "", []) is None


def test_poll_stores_tags_and_alerts_once(nexus_db, monkeypatch):
    now = datetime.now(timezone.utc)
    payload = _rss([
        ("Nvidia names Jensen Huang CEO again", "https://x/nvda", now - timedelta(minutes=3)),
        ("Nvidia CEO Jensen Huang named CEO again", "https://y/nvda", now - timedelta(minutes=2)),  # same story
        ("Apple CEO Tim Cook to retire", "https://x/old", now - timedelta(hours=5)),  # too old to alert
        ("Markets drift", "https://x/drift", now),
    ])

    class Response:
        status_code = 200
        content = payload
        headers = {"ETag": "abc"}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(wire, "FEEDS", [wire.Feed("test", "https://feed", "outlet")])
    monkeypatch.setattr(wire.requests, "get", lambda *a, **k: Response())
    wire._state.clear()
    seq = live.current_seq()

    result = wire.poll(force=True)
    assert result["new"] == 4 and result["alerts"] == 1
    alerts = [e for e in live.wait(seq, 0) if e["topic"] == "alert"]
    assert len(alerts) == 1 and alerts[0]["alert"]["tickers"] == ["stock:nvda"]
    stored = wire.recent_alerts()
    assert len(stored) == 1 and "leadership" in stored[0]["kinds"]
    assert db.one("SELECT COUNT(*) c FROM news WHERE fetched_at IS NOT NULL")["c"] == 4

    assert wire.poll(force=True)["new"] == 0  # nothing re-alerts

    # Another outlet with a different headline about the same event: stored as a follow-up, no new alert.
    payload2 = _rss([("Jensen Huang reinstated as Nvidia chief executive", "https://z/nvda", now)])
    monkeypatch.setattr(Response, "content", payload2)
    seq = live.current_seq()
    assert wire.poll(force=True)["alerts"] == 0
    assert not [e for e in live.wait(seq, 0) if e["topic"] == "alert"]
    assert wire.recent_alerts()[0]["follow_ups"] == 1
    assert wire.sources()[0]["failures"] == 0


def test_failed_feed_backs_off(nexus_db, monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(wire, "FEEDS", [wire.Feed("bad", "https://bad", "outlet", 60)])
    monkeypatch.setattr(wire.requests, "get", boom)
    wire._state.clear()
    assert wire.poll(force=True)["failed"] == 1
    assert wire._state["bad"]["next"] > wire.time.time() + 100  # 60s * 2^1
    assert wire.poll()["feeds"] == 0  # not due yet
