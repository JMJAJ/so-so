"""Trading hours of the world's main markets, in each market's own time zone (DST-aware).

Sessions are defined in local wall-clock time and converted to UTC per date, so daylight
saving shifts are handled by zoneinfo. US exchange holidays and early closes are included
(they decide when paper orders fill); other exchanges' holidays are not.

Which market each NEXUS instrument trades on:
  stock / etf -> nyse, forex -> forex, commodity (futures) -> cme, crypto -> crypto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

Session = tuple[str, str]  # local "HH:MM" open, close ("24:00" = midnight)
WEEKDAYS = (0, 1, 2, 3, 4)

US_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
    "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05",
    "2027-09-06", "2027-11-25", "2027-12-24",
}
US_EARLY_CLOSE = {"2026-11-27": "13:00", "2026-12-24": "13:00", "2027-11-26": "13:00"}


@dataclass(frozen=True)
class Market:
    id: str
    name: str
    city: str
    tz: str
    kind: str  # exchange | forex | futures | crypto
    # weekday (0 = Monday) -> regular sessions in local time
    sessions: dict[int, tuple[Session, ...]]
    extended: dict[int, tuple[Session, ...]] = field(default_factory=dict)
    us_calendar: bool = False
    note: str = ""


def _weekdays(*sessions: Session) -> dict[int, tuple[Session, ...]]:
    return {d: sessions for d in WEEKDAYS}


MARKETS: tuple[Market, ...] = (
    Market("nyse", "NYSE / Nasdaq", "New York", "America/New_York", "exchange",
           _weekdays(("09:30", "16:00")), extended=_weekdays(("04:00", "09:30"), ("16:00", "20:00")),
           us_calendar=True, note="US stocks and ETFs. Paper orders fill in the regular session only."),
    Market("tsx", "Toronto (TSX)", "Toronto", "America/Toronto", "exchange", _weekdays(("09:30", "16:00"))),
    Market("lse", "London (LSE)", "London", "Europe/London", "exchange", _weekdays(("08:00", "16:30"))),
    Market("xetra", "Frankfurt (Xetra)", "Frankfurt", "Europe/Berlin", "exchange", _weekdays(("09:00", "17:30"))),
    Market("euronext", "Euronext Paris", "Paris", "Europe/Paris", "exchange", _weekdays(("09:00", "17:30"))),
    Market("nse", "India (NSE)", "Mumbai", "Asia/Kolkata", "exchange", _weekdays(("09:15", "15:30"))),
    Market("sse", "Shanghai (SSE)", "Shanghai", "Asia/Shanghai", "exchange",
           _weekdays(("09:30", "11:30"), ("13:00", "15:00"))),
    Market("hkex", "Hong Kong (HKEX)", "Hong Kong", "Asia/Hong_Kong", "exchange",
           _weekdays(("09:30", "12:00"), ("13:00", "16:00"))),
    Market("tse", "Tokyo (TSE)", "Tokyo", "Asia/Tokyo", "exchange",
           _weekdays(("09:00", "11:30"), ("12:30", "15:30"))),
    Market("asx", "Sydney (ASX)", "Sydney", "Australia/Sydney", "exchange", _weekdays(("10:00", "16:00"))),
    Market("forex", "Forex (24/5)", "Global", "America/New_York", "forex",
           {6: (("17:00", "24:00"),), 0: (("00:00", "24:00"),), 1: (("00:00", "24:00"),),
            2: (("00:00", "24:00"),), 3: (("00:00", "24:00"),), 4: (("00:00", "17:00"),)},
           note="Sunday 17:00 to Friday 17:00 New York time."),
    Market("cme", "CME Globex futures", "Chicago", "America/New_York", "futures",
           {6: (("18:00", "24:00"),), **{d: (("00:00", "17:00"), ("18:00", "24:00")) for d in (0, 1, 2, 3)},
            4: (("00:00", "17:00"),)},
           note="Commodity futures: nearly 24h with a daily 17:00-18:00 New York break."),
    Market("crypto", "Crypto (24/7)", "Global", "UTC", "crypto", {d: (("00:00", "24:00"),) for d in range(7)}),
)
BY_ID = {m.id: m for m in MARKETS}
SESSION_MARKET = {"us_equities": "nyse", "forex": "forex", "futures": "cme", "always": "crypto"}


def _at(day: date, hhmm: str, tz: ZoneInfo) -> datetime:
    if hhmm == "24:00":
        return datetime.combine(day + timedelta(days=1), time(0), tz).astimezone(timezone.utc)
    hour, minute = map(int, hhmm.split(":"))
    return datetime.combine(day, time(hour, minute), tz).astimezone(timezone.utc)


def _merge(spans: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def intervals(market: Market, start: datetime, end: datetime, extended: bool = False) -> list[tuple[datetime, datetime]]:
    """UTC (open, close) spans of the market's regular (or extended-hours) sessions overlapping [start, end]."""
    tz = ZoneInfo(market.tz)
    table = market.extended if extended else market.sessions
    day, last = start.astimezone(tz).date() - timedelta(days=1), end.astimezone(tz).date()
    spans = []
    while day <= last:
        iso = day.isoformat()
        if not (market.us_calendar and iso in US_HOLIDAYS):
            for open_, close in table.get(day.weekday(), ()):
                if market.us_calendar and not extended and iso in US_EARLY_CLOSE:
                    close = min(close, US_EARLY_CLOSE[iso])
                spans.append((_at(day, open_, tz), _at(day, close, tz)))
        day += timedelta(days=1)
    return [(a, b) for a, b in _merge(spans) if b > start and a < end]


def is_open(market_id: str, when: datetime | None = None) -> bool:
    now = when or datetime.now(timezone.utc)
    return any(a <= now < b for a, b in intervals(BY_ID[market_id], now - timedelta(days=1), now + timedelta(days=1)))


def status(market: Market, now: datetime | None = None, days_back: float = 2.5, days_ahead: float = 8) -> dict:
    now = now or datetime.now(timezone.utc)
    spans = intervals(market, now - timedelta(days=days_back), now + timedelta(days=days_ahead))
    current = next(((a, b) for a, b in spans if a <= now < b), None)
    upcoming = next(((a, b) for a, b in spans if a > now), None)
    extended = intervals(market, now - timedelta(days=days_back), now + timedelta(days=days_ahead), extended=True)
    local = now.astimezone(ZoneInfo(market.tz))
    opens_today = bool(upcoming) and upcoming[0].astimezone(local.tzinfo).date() == local.date()
    closed_today = any(b <= now and b.astimezone(local.tzinfo).date() == local.date() for _, b in spans)
    phase = "open" if current else "closed"
    if not current and any(a <= now < b for a, b in extended):
        phase = "pre-market" if opens_today else "after-hours"
    elif not current and market.kind == "exchange" and opens_today and closed_today:
        phase = "lunch break"
    iso = lambda value: value.isoformat(timespec="minutes") if value else None  # noqa: E731
    return {
        "id": market.id, "name": market.name, "city": market.city, "tz": market.tz, "kind": market.kind,
        "note": market.note, "holidays_known": market.us_calendar or market.kind == "crypto",
        "open": bool(current), "phase": phase,
        "local_time": local.strftime("%H:%M"), "local_weekday": local.strftime("%a"),
        "tz_abbr": local.tzname(),
        "regular_hours": {str(d): [list(s) for s in sessions] for d, sessions in market.sessions.items()},
        "closes_at": iso(current[1]) if current else None,
        "opens_at": iso(upcoming[0]) if not current and upcoming else None,
        "next_session": [iso(upcoming[0]), iso(upcoming[1])] if upcoming else None,
        "intervals": [[iso(a), iso(b)] for a, b in spans],
        "extended_intervals": [[iso(a), iso(b)] for a, b in extended],
    }


def overview(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {"now": now.isoformat(timespec="seconds"), "markets": [status(m, now) for m in MARKETS]}
