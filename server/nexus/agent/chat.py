"""Conversational research assistant with the same tools as the analyst.

History is stored append-only (including provider-native blocks), so follow-up
questions keep full context.
"""

from __future__ import annotations

import uuid
from typing import Callable

from .. import accounts, config, db, llm, paper, recommendations
from . import loop, tools

SLASH = {
    "/scan": "Scan the universe{arg} and show the most interesting candidates in a table with the key evidence for each.",
    "/why": "Do a full evidence review of {arg}: asset_snapshot, event_effects, analogs, correlations, recent_news. "
            "Give a verdict (long / short / no trade) with the numbers behind it.",
    "/regime": "Summarise the current macro regime and what historically follows similar regimes.",
    "/news": "What are the most important classified headlines{arg} from the last 3 days, and what did similar events do historically?",
    "/backtest": "Show model_validation{arg} and explain plainly which signals have a real out-of-sample edge and which don't.",
    "/record": "Show my track record and what it says about which evidence works.",
    "/portfolio": "Review my paper portfolio: positions, risk, and anything that looks invalidated.",
    "/review": "Load position-review and review every open recommendation{arg}. Close one with close_recommendation "
               "only if its invalidation condition has actually happened; otherwise hold. End with the summary table.",
    "/skills": "List the skills you can load and, from track_record by_skill, how calls made with each have done.",
    "/recommend": "Investigate {arg} and, if the evidence is strong enough, record a recommendation with propose_recommendation.",
    "/invest": "Find the best paper investments to make right now{arg}. Start with scan_universe and macro_regime, then "
               "investigate the 3-6 strongest candidates (event_effects, analogs, correlations, recent_news). Record up to "
               "{max_recs} with propose_recommendation, only where several independent kinds of evidence agree; autopilot "
               "opens a paper position for each. For every trade you record, call show_chart (kind=price) for it. Finish "
               "with a table of the trades (entry, stop, target, probability, key evidence) and the candidates you "
               "rejected and why. Recording zero trades is fine if nothing has real evidence.",
    "/chart": "Show {arg} with show_chart (pick the most fitting kind), then explain what it shows in 2-4 sentences.",
}

CHAT_EXTRA = """You are talking with the user directly. Use tools before answering factual questions
about markets; do not answer from memory. Only call propose_recommendation when the user asks you to
recommend, invest or trade (or uses /recommend or /invest), and close_recommendation only when the user asks
to review or close positions (/review). Load the matching skill first. Use show_chart when the user asks to see
something or when a chart makes the answer clearer."""


def expand(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return text
    command, _, arg = stripped.partition(" ")
    template = SLASH.get(command.lower())
    if not template:
        return text
    arg = arg.strip()
    if command.lower() in ("/scan", "/news", "/backtest", "/invest", "/review", "/skills"):
        return template.format(arg=f" (focus: {arg})" if arg else "", max_recs=config.get_int("analyst_max_recs"))
    if command.lower() == "/chart":
        return template.format(arg=arg or "my paper equity vs the S&P 500")
    return template.format(arg=arg or "the strongest current candidate")


def _account_note() -> str:
    account = accounts.get()
    state = paper.portfolio(mark=False, account_id=account["id"])
    note = (f"Paper account in use: {account['name']} (equity ${state['equity']:,.2f}, "
            f"{state['open_count'] + state['pending_count']} positions, autopilot "
            f"{'on' if account['autopilot'] else 'off'}, trade gate {account['gate']}).")
    if account["gate"] == "any":
        note += (" This account accepts any trade: when the user explicitly asks you to open a trade, run the "
                 "checklist, tell them which checks fail and the computed probability and expected value, then "
                 "call propose_recommendation anyway. Never claim a failing trade has an edge.")
    return note


def new_conversation(title: str = "New chat") -> str:
    conv_id = f"conv_{uuid.uuid4().hex[:10]}"
    now = db.now_iso()
    db.execute("INSERT INTO conversations(id,title,created_at,updated_at) VALUES(?,?,?,?)", (conv_id, title[:80], now, now))
    return conv_id


def history(conv_id: str) -> list[dict]:
    return [db.loads(row["content"]) for row in
            db.rows("SELECT content FROM messages WHERE conversation_id=? ORDER BY id", (conv_id,))]


def conversations() -> list[dict]:
    return db.rows("SELECT * FROM conversations ORDER BY updated_at DESC LIMIT 100")


def public_messages(conv_id: str) -> list[dict]:
    """Messages shaped for the UI: one assistant bubble per user turn (all its steps merged),
    with the tool trace and any charts, matching what the live stream shows."""
    out: list[dict] = []
    for message in history(conv_id):
        if message["role"] == "user":
            out.append({"role": "user", "text": message.get("display") or message["text"]})
            continue
        if not out or out[-1]["role"] != "assistant":
            out.append({"role": "assistant", "text": "", "tools": [], "charts": []})
        bubble = out[-1]
        if message["role"] == "assistant":
            if message.get("text"):
                bubble["text"] = "\n\n".join(filter(None, [bubble["text"], message["text"]]))
            bubble["tools"] += [{"id": c["id"], "name": c["name"], "input": c["input"]} for c in message.get("tool_calls") or []]
        elif message["role"] == "tool":
            bubble["charts"] += message.get("charts", [])
            errors = {r["id"] for r in message["results"] if r.get("is_error")}
            for tool in bubble["tools"]:
                if tool.get("id") in errors:
                    tool["is_error"] = True
    return out


def send(conv_id: str | None, text: str, on_event: Callable[[dict], None] | None = None) -> dict:
    if not conv_id or not db.one("SELECT 1 FROM conversations WHERE id=?", (conv_id,)):
        conv_id = new_conversation(text.strip()[:60] or "New chat")
    messages = history(conv_id)
    user = {"role": "user", "text": expand(text)}
    if user["text"] != text:
        user["display"] = text
    messages.append(user)
    stored_from = len(messages) - 1
    system = loop.system_prompt(CHAT_EXTRA + "\n\n" + _account_note() + "\n\nTrack record so far:\n"
                                + recommendations.lessons())
    try:
        loop.run(llm.create("main"), system, messages, tool_specs=tools.specs(), on_event=on_event,
                 tool_extra={"_source": "chat"}, effort="medium", max_steps=40)
    except Exception as exc:
        # Drop the half-finished turn (it may end in unanswered tool calls) and record the failure.
        del messages[stored_from + 1:]
        messages.append({"role": "assistant", "text": f"[error: {exc}]", "tool_calls": [], "native": None})
        if on_event:
            on_event({"type": "error", "message": str(exc)})
    now = db.now_iso()
    db.executemany("INSERT INTO messages(conversation_id,role,content,created_at) VALUES(?,?,?,?)",
                   [(conv_id, m["role"], db.dumps(m), now) for m in messages[stored_from:]])
    db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conv_id))
    final = next((m.get("text", "") for m in reversed(messages) if m["role"] == "assistant"), "")
    return {"conversation_id": conv_id, "text": final}
