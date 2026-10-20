"""Event taxonomy.

`EVENT_TYPES` are structured events with measurable history (detected from prices,
FRED, earnings and GDELT). `NEWS_CATEGORIES` are what the LLM tags headlines with;
each maps to the historical event types whose measured impact is the best
available evidence for it (or none, which the analyst must say out loud).
"""

from __future__ import annotations

EVENT_TYPES: dict[str, dict] = {
    # Company
    "earnings_beat": {"scope": "asset", "label": "Earnings beat (EPS surprise > +2%)"},
    "earnings_miss": {"scope": "asset", "label": "Earnings miss (EPS surprise < -2%)"},
    # Central bank
    "rate_hike": {"scope": "macro", "label": "Fed rate hike"},
    "rate_cut": {"scope": "macro", "label": "Fed rate cut"},
    # Macro data (release dates approximate, revised data)
    "inflation_hot": {"scope": "macro", "label": "CPI hotter than trend"},
    "inflation_cool": {"scope": "macro", "label": "CPI cooler than trend"},
    "jobs_strong": {"scope": "macro", "label": "Payrolls stronger than trend"},
    "jobs_weak": {"scope": "macro", "label": "Payrolls weaker than trend"},
    # Market shocks (exact dates, from prices)
    "vix_spike": {"scope": "macro", "label": "Volatility spike (VIX jumps >40% over 20d avg)"},
    "equity_selloff": {"scope": "macro", "label": "Sharp S&P 500 selloff (5d move < -2.5σ)"},
    "oil_shock_up": {"scope": "macro", "label": "Oil price spike (5d move > +2.5σ)"},
    "oil_shock_down": {"scope": "macro", "label": "Oil price collapse (5d move < -2.5σ)"},
    "yield_spike": {"scope": "macro", "label": "10Y yield jump (5d move > +2.5σ)"},
    "yield_drop": {"scope": "macro", "label": "10Y yield drop (5d move < -2.5σ)"},
    "dollar_surge": {"scope": "macro", "label": "Dollar surge (5d move > +2.5σ)"},
    "dollar_slump": {"scope": "macro", "label": "Dollar slump (5d move < -2.5σ)"},
    "credit_stress": {"scope": "macro", "label": "High-yield spreads widen sharply"},
    "crypto_crash": {"scope": "macro", "label": "Bitcoin crash (3d move < -2.5σ)"},
    "crypto_surge": {"scope": "macro", "label": "Bitcoin surge (3d move > +2.5σ)"},
    # Geopolitics (GDELT spikes vs trailing 90d)
    "geopolitical_escalation": {"scope": "global", "label": "Global armed-conflict news spike"},
    "mideast_escalation": {"scope": "global", "label": "Middle East conflict news spike"},
    "russia_ukraine_escalation": {"scope": "global", "label": "Russia/Ukraine conflict news spike"},
    "us_china_tension": {"scope": "global", "label": "US–China conflictual news spike"},
    "sanctions_wave": {"scope": "global", "label": "Sanctions/embargo news spike"},
    "unrest_spike": {"scope": "global", "label": "Protest/unrest news spike"},
}

NEWS_CATEGORIES: dict[str, list[str]] = {
    "earnings_beat": ["earnings_beat"],
    "earnings_miss": ["earnings_miss"],
    "guidance_raise": ["earnings_beat"],
    "guidance_cut": ["earnings_miss"],
    "fed_hawkish": ["rate_hike", "yield_spike"],
    "fed_dovish": ["rate_cut", "yield_drop"],
    "rate_hike": ["rate_hike"],
    "rate_cut": ["rate_cut"],
    "inflation_hot": ["inflation_hot"],
    "inflation_cool": ["inflation_cool"],
    "jobs_strong": ["jobs_strong"],
    "jobs_weak": ["jobs_weak"],
    "geopolitical_escalation": ["geopolitical_escalation", "mideast_escalation", "russia_ukraine_escalation"],
    "geopolitical_deescalation": [],
    "sanctions": ["sanctions_wave"],
    "trade_tariffs": ["us_china_tension"],
    "oil_supply_shock": ["oil_shock_up"],
    "oil_demand_drop": ["oil_shock_down"],
    "credit_stress": ["credit_stress"],
    "market_selloff": ["equity_selloff", "vix_spike"],
    "crypto_regulation": [],
    "crypto_hack": ["crypto_crash"],
    "regulatory_action": [],
    "litigation": [],
    "merger_acquisition": [],
    "product_launch": [],
    "analyst_upgrade": [],
    "analyst_downgrade": [],
    "management_change": [],
    "other": [],
}


def label(event_type: str) -> str:
    return EVENT_TYPES.get(event_type, {}).get("label", event_type)
