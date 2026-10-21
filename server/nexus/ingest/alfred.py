"""ALFRED (FRED's vintage archive): macro figures as first published, with their real
release dates. Needs a free FRED API key (`FRED_API_KEY`, or Settings).

Revised data leaks hindsight into event studies: a CPI print that looked hot on release
day may be revised to normal later. Using first releases, dated by when they were
published, makes macro-surprise events point-in-time.
"""

from __future__ import annotations

import pandas as pd
import requests

from .. import config, db

URL = "https://api.stlouisfed.org/fred/series/observations"


def first_releases(series_id: str, start: str = "2008-01-01") -> pd.DataFrame | None:
    """Columns: value (first print), released (publication date). Index: observation date.
    Returns None when no key is configured or the request fails."""
    key = config.secret("fred_api_key")
    if not key:
        return None
    try:
        response = requests.get(URL, timeout=60, params={
            "series_id": series_id, "api_key": key, "file_type": "json",
            "output_type": 4,  # initial release only
            "realtime_start": "1776-07-04", "realtime_end": "9999-12-31",
            "observation_start": start,
        })
        response.raise_for_status()
        rows = response.json().get("observations", [])
    except Exception as exc:
        db.log("warn", "alfred", f"{series_id}: {exc}")
        return None
    frame = pd.DataFrame(rows)
    if frame.empty:
        return None
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["value"])
    frame.index = pd.to_datetime(frame["date"])
    frame["released"] = pd.to_datetime(frame["realtime_start"])
    return frame[["value", "released"]].sort_index()
