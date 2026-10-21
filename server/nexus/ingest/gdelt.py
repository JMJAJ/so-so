"""GDELT: daily geopolitical theme intensity (history) and recent headlines.

History comes from the GDELT 1.0 daily event exports (~4 MB/day). Each file is
aggregated into a handful of theme counts and discarded, so the archive costs a
few KB per day. A file's date is when its events were *published*, which keeps the
series point-in-time.
"""

from __future__ import annotations

import io
import time
import zipfile
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

from .. import db
from .news import store_articles

EXPORT_URL = "http://data.gdeltproject.org/events/{day}.export.CSV.zip"
DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Column positions in the 58-column daily export.
COLS = {1: "sqldate", 7: "a1country", 17: "a2country", 25: "root", 26: "code", 28: "rootcode",
        29: "quad", 30: "goldstein", 33: "articles", 34: "tone", 51: "geo"}
MIDEAST = {"IS", "IR", "IZ", "SY", "LE", "YM", "SA", "GZ", "WE", "JO", "KU", "QA", "AE"}
RUS_UKR = {"RS", "UP"}


def _aggregate(frame: pd.DataFrame) -> dict[str, tuple[float, float, float]]:
    frame = frame[frame["root"] == 1]
    frame = frame.assign(articles=frame["articles"].fillna(1).clip(lower=1))
    material_violence = frame["rootcode"].astype(str).isin(["18", "19", "20"])
    conflict_quads = frame["quad"].isin([3, 4])
    us_china = (
        ((frame["a1country"] == "USA") & (frame["a2country"] == "CHN"))
        | ((frame["a1country"] == "CHN") & (frame["a2country"] == "USA"))
        | ((frame["a1country"] == "CHN") & (frame["a2country"] == "TWN"))
    ) & conflict_quads
    masks = {
        "_total": pd.Series(True, index=frame.index),
        "global_conflict": material_violence,
        "mideast_conflict": material_violence & frame["geo"].isin(MIDEAST),
        "russia_ukraine_conflict": material_violence & frame["geo"].isin(RUS_UKR),
        "us_china_conflict": us_china,
        "sanctions": frame["code"].astype(str).str.startswith("163"),
        "protest": frame["rootcode"].astype(str) == "14",
    }
    result = {}
    for theme, mask in masks.items():
        subset = frame[mask]
        weight = subset["articles"]
        total = float(weight.sum())
        tone = float((subset["tone"] * weight).sum() / total) if total else None
        goldstein = float((subset["goldstein"] * weight).sum() / total) if total else None
        result[theme] = (total, tone, goldstein)
    return result


def fetch_day(day: date) -> bool:
    url = EXPORT_URL.format(day=day.strftime("%Y%m%d"))
    try:
        response = requests.get(url, timeout=120)
        if response.status_code == 404:
            return False
        response.raise_for_status()
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        frame = pd.read_csv(
            archive.open(archive.namelist()[0]), sep="\t", header=None, usecols=list(COLS),
            low_memory=False, on_bad_lines="skip",
        ).rename(columns=COLS)
    except Exception as exc:
        db.log("warn", "gdelt", f"{day}: {exc}")
        return False
    db.executemany(
        "INSERT OR REPLACE INTO theme_series(theme, date, count, tone, goldstein) VALUES(?,?,?,?,?)",
        [(theme, day.isoformat(), *values) for theme, values in _aggregate(frame).items()],
    )
    return True


def update_themes(days: int, progress=None, deadline_s: float | None = None) -> dict:
    """Fill missing days going backwards from yesterday. Resumable; stops at deadline."""
    have = {row["date"] for row in db.rows("SELECT date FROM theme_series WHERE theme='_total'")}
    started = time.time()
    fetched = skipped = 0
    for back in range(1, days + 1):
        day = date.today() - timedelta(days=back)
        if day.isoformat() in have:
            skipped += 1
            continue
        if deadline_s and time.time() - started > deadline_s:
            break
        if progress:
            progress(f"gdelt {day}")
        fetched += int(fetch_day(day))
    return {"fetched": fetched, "already_had": skipped}


# ── Headlines (DOC API, rolling 3 months, rate limited to 1 req / 5 s) ─────

DOC_QUERIES = {
    "macro": '("federal reserve" OR inflation OR "interest rates" OR recession) sourcelang:english',
    "geopolitics": '(sanctions OR missile OR invasion OR ceasefire OR tariffs) sourcelang:english',
    "energy": '(OPEC OR "oil prices" OR "natural gas prices") sourcelang:english',
    "markets": '("stock market" OR "wall street" OR "treasury yields") sourcelang:english',
    "crypto": '(bitcoin OR ethereum OR crypto) (price OR etf OR sec) sourcelang:english',
}


def backfill_doc_headlines(days: int = 90, progress=None) -> int:
    """GDELT DOC headlines one week at a time (the API only reaches back about three months)."""
    end = datetime.now(timezone.utc)
    stored = 0
    for week in range(0, days, 7):
        if progress:
            progress(f"gdelt headlines week {week // 7 + 1}/{days // 7}")
        stored += fetch_doc_headlines(max_records=75, start=end - timedelta(days=week + 7),
                                      end=end - timedelta(days=week))
    return stored


def fetch_doc_headlines(timespan: str = "1d", max_records: int = 50, start: datetime | None = None,
                        end: datetime | None = None) -> int:
    window = ({"startdatetime": start.strftime("%Y%m%d%H%M%S"), "enddatetime": end.strftime("%Y%m%d%H%M%S")}
              if start and end else {"timespan": timespan})
    stored = 0
    for name, query in DOC_QUERIES.items():
        for attempt in range(2):
            try:
                response = requests.get(
                    DOC_URL, timeout=30,
                    params={"query": query, "mode": "artlist", "format": "json",
                            "maxrecords": max_records, "sort": "datedesc", **window},
                )
                if response.status_code == 429:
                    time.sleep(10)
                    continue
                response.raise_for_status()
                articles = response.json().get("articles", [])
            except Exception as exc:
                db.log("warn", "gdelt-doc", f"{name}: {exc}")
                break
            stored += store_articles([
                {
                    "title": item.get("title", ""),
                    "url": item.get("url"),
                    "source": item.get("domain"),
                    "published_at": pd.to_datetime(item.get("seendate"), format="%Y%m%dT%H%M%SZ", utc=True).isoformat(),
                    "provider": f"gdelt:{name}",
                }
                for item in articles if item.get("title") and item.get("language", "English") == "English"
            ])
            break
        time.sleep(6)
    return stored
