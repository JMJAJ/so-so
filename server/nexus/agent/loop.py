"""Provider-neutral tool-use loop shared by the analyst and chat."""

from __future__ import annotations

import json
from datetime import date
from typing import Callable

from .. import llm
from . import factcheck, tools

PRINCIPLES = f"""You are NEXUS, the research analyst inside a paper-trading terminal. Today is {{today}}.
Your job is to find what is most worth investing in over the next 1–8 weeks across stocks, ETFs,
crypto, FX and commodities, and to be honest about how strong the evidence is.

How you work:
- Ground every claim in tool results. Quote the numbers (n, hit rate, edge, t-stat, IC). If a tool
  shows n < 8 or |t| < 2, say the evidence is weak; do not dress it up.
- Connect today's news to history: recent_news tells you which historical event types a headline maps
  to; event_study/event_effects tell you what those events did to an asset before. analogs shows what
  happened after similar market states. correlations shows co-movement and lead-lag drivers.
- The quant model was validated walk-forward. When model_has_edge is false for an asset class, its
  forecast is only the base rate; weigh event, analog and news evidence instead.
- Learn from the track record: if a kind of evidence has been losing money, discount it.
- Probabilities you state must be calibrated: 0.55 means 55 of 100 such calls win. Most real edges
  are small (0.52–0.62). Stops must sit where the thesis is wrong (≈1.5–2.5× daily ATR away); targets
  should give reward/risk ≥ 1.5.
- This is paper trading for research. You are not a licensed advisor; say so if asked for personal advice.
Write plainly and compactly. Use markdown tables for comparisons, and show_chart when a picture helps
(the user sees the chart; don't repeat all its numbers)."""


def system_prompt(extra: str = "") -> str:
    return PRINCIPLES.replace("{today}", date.today().isoformat()) + ("\n\n" + extra if extra else "")


def run(
    provider: llm.Provider,
    system: str,
    history: list[dict],
    *,
    tool_specs: list[dict],
    max_steps: int = 24,
    on_event: Callable[[dict], None] | None = None,
    tool_extra: dict | None = None,
    guard: Callable[[str, dict], str | None] | None = None,
    effort: str | None = None,
) -> list[dict]:
    """Run until the model stops calling tools. Appends to `history` in place and returns new messages."""
    emit = on_event or (lambda _event: None)
    new: list[dict] = []
    for _ in range(max_steps):
        reply = provider.complete(system, history, tool_specs,
                                  on_text=lambda chunk: emit({"type": "text", "text": chunk}), effort=effort)
        message = reply.as_message()
        if not reply.tool_calls and reply.text and new:
            # Verify the final answer's numbers against this turn's tool data.
            result = factcheck.check(reply.text, factcheck.tool_blobs(new))
            addendum = factcheck.note(result)
            if addendum:
                message["text"] = reply.text + addendum
                emit({"type": "text", "text": addendum})
            emit({"type": "fact_check", **result})
        history.append(message)
        new.append(message)
        if not reply.tool_calls:
            emit({"type": "done", "stop_reason": reply.stop_reason})
            return new
        results, charts = [], []
        for call in reply.tool_calls:
            emit({"type": "tool_call", "id": call["id"], "name": call["name"], "input": call["input"]})
            blocked = guard(call["name"], call["input"]) if guard else None
            if blocked:
                content, is_error = f'{{"error": "{blocked}"}}', True
            else:
                content, is_error = tools.call(call["name"], call["input"], extra=tool_extra)
            if call["name"] == "show_chart" and not is_error:
                # The chart goes to the UI; the model only needs the summary.
                payload = json.loads(content)
                charts.append(payload["chart"])
                emit({"type": "chart", "id": call["id"], "chart": payload["chart"]})
                content = json.dumps({"summary": payload["summary"]})
            emit({"type": "tool_result", "id": call["id"], "name": call["name"], "is_error": is_error,
                  "preview": content[:600]})
            results.append({"id": call["id"], "name": call["name"], "content": content, "is_error": is_error})
        tool_message = {"role": "tool", "results": results}
        if charts:
            tool_message["charts"] = charts
        history.append(tool_message)
        new.append(tool_message)
    emit({"type": "done", "stop_reason": "max_steps"})
    return new
