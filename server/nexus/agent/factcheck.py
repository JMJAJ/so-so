"""Check the numbers an AI answer quotes against the tool results it actually received.

Free models misread their tools (wrong n, invented t-stats). After each answer, every
quoted t-stat (`t −2.9`, `t=3.1`), sample size (`n=22`, `n 22`) and percentage is looked
up in that turn's tool data; anything that can't be found is listed under the answer.
A number matches if it agrees to the precision it was written with.
"""

from __future__ import annotations

import json
import re

_NUM = r"[+\-]?\d+(?:\.\d+)?"
T_CLAIM = re.compile(r"\bt\s*(?:-stat)?\s*[=≈:]?\s*(" + _NUM + r")(?![\d%])", re.IGNORECASE)
N_CLAIM = re.compile(r"\bn\s*[=:]?\s*(\d+)\b")
PCT_CLAIM = re.compile(r"(" + _NUM + r")\s*%")
NUMBER = re.compile(_NUM)


def _normalise(text: str) -> str:
    return text.replace("−", "-").replace("–", "-")


def _decimals(raw: str) -> int:
    return len(raw.split(".")[1]) if "." in raw else 0


def known_numbers(blobs: list[str]) -> list[float]:
    """Every number in the tool data, plus fractions scaled to percent (0.047 -> 4.7)."""
    values: list[float] = []
    for blob in blobs:
        for raw in NUMBER.findall(_normalise(blob)):
            try:
                value = float(raw)
            except ValueError:
                continue
            values.append(value)
            if abs(value) <= 5:
                values.append(value * 100)
    return values


def _supported(claim: float, decimals: int, pool: list[float], absolute: bool = False) -> bool:
    tolerance = 0.5 * 10 ** (-decimals) + 1e-9
    for value in pool:
        if abs(value - claim) <= tolerance or (absolute and abs(abs(value) - abs(claim)) <= tolerance):
            return True
    return False


def check(answer: str, tool_blobs: list[str]) -> dict:
    text = _normalise(answer)
    pool = known_numbers(tool_blobs)
    checked, unsupported = 0, []
    for raw in T_CLAIM.findall(text):
        checked += 1
        if not _supported(float(raw), _decimals(raw), pool, absolute=True):
            unsupported.append(f"t {raw}")
    for raw in N_CLAIM.findall(text):
        checked += 1
        if not _supported(float(raw), 0, pool):
            unsupported.append(f"n {raw}")
    for raw in PCT_CLAIM.findall(text):
        checked += 1
        # A signed percent may be quoted without its sign ("lagged by 2.8%").
        if not _supported(float(raw), _decimals(raw), pool, absolute=True):
            unsupported.append(f"{raw}%")
    return {"checked": checked, "unsupported": sorted(set(unsupported)), "ok": not unsupported}


def tool_blobs(messages: list[dict]) -> list[str]:
    blobs: list[str] = []
    for message in messages:
        if message.get("role") == "tool":
            blobs.extend(result.get("content", "") for result in message.get("results", []))
        elif message.get("role") == "assistant":
            blobs.extend(json.dumps(call.get("input", {})) for call in message.get("tool_calls") or [])
    return blobs


def note(result: dict) -> str:
    if not result["checked"]:
        return ""
    if result["ok"]:
        return f"\n\n> Fact check: all {result['checked']} quoted numbers match the tool data."
    missing = ", ".join(result["unsupported"][:8])
    more = f" (+{len(result['unsupported']) - 8} more)" if len(result["unsupported"]) > 8 else ""
    return (f"\n\n> **Fact check:** {len(result['unsupported'])} of {result['checked']} quoted numbers were not "
            f"found in the tool data: {missing}{more}. Treat them as unverified.")
