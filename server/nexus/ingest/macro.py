"""FRED macro series via the keyless fredgraph CSV endpoint."""

from __future__ import annotations

import io

import pandas as pd
import requests

from .. import db

FRED_SERIES = {
    "DFEDTARU": "Fed funds target (upper)",
    "DGS10": "10Y Treasury yield",
    "DGS2": "2Y Treasury yield",
    "T10Y2Y": "10Y-2Y curve",
    "T10YIE": "10Y breakeven inflation",
    "BAMLH0A0HYM2": "High-yield credit spread",
    "DTWEXBGS": "Broad US dollar index",
    "CPIAUCSL": "CPI (all items)",
    "CPILFESL": "Core CPI",
    "PAYEMS": "Nonfarm payrolls",
    "UNRATE": "Unemployment rate",
    "ICSA": "Initial jobless claims",
    "INDPRO": "Industrial production",
    "RSAFS": "Retail sales",
    "UMCSENT": "Consumer sentiment",
}
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def update_macro(start: str = "2008-01-01") -> dict:
    stored, failed = 0, []
    for series_id in FRED_SERIES:
        try:
            response = requests.get(URL, params={"id": series_id, "cosd": start}, timeout=30)
            response.raise_for_status()
            frame = pd.read_csv(io.StringIO(response.text))
        except Exception as exc:
            db.log("warn", "macro", f"{series_id}: {exc}")
            failed.append(series_id)
            continue
        frame.columns = ["date", "value"]
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
        frame = frame.dropna()
        db.executemany(
            "INSERT OR REPLACE INTO macro_series(series_id, date, value) VALUES(?,?,?)",
            [(series_id, str(row.date)[:10], float(row.value)) for row in frame.itertuples()],
        )
        stored += len(frame)
    return {"rows": stored, "failed": failed}
