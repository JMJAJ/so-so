"""Skills: short playbooks the AI loads on demand before a task.

Each skill is a markdown file in `nexus/skills/` with a front matter header:

    ---
    name: pre-trade-checklist
    version: 1
    description: one line shown in the catalog
    when: the task that should trigger it
    ---
    body (the instructions the model receives from load_skill)

The system prompt lists only names and descriptions; the body is loaded with the
`load_skill` tool. Skills can also be generated from data (see GENERATED), in which case
the version is a hash of the generated text, so a changed playbook counts as a new version.

Every recommendation records the skills that were loaded when it was made (`name@version`),
so the track record can show whether a skill actually improves results.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import db
from ..research import event_study
from ..taxonomy import EVENT_TYPES

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


@dataclass(frozen=True)
class Skill:
    name: str
    version: str
    description: str
    when: str
    body: str

    @property
    def tag(self) -> str:
        return f"{self.name}@{self.version}"


def _parse(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    header, _, body = text[3:].partition("\n---")
    meta = {}
    for line in header.strip().splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, body.strip()


def _file_skills() -> dict[str, Skill]:
    out = {}
    for path in sorted(SKILLS_DIR.glob("*.md")):
        meta, body = _parse(path.read_text(encoding="utf-8"))
        name = meta.get("name") or path.stem
        out[name] = Skill(name, str(meta.get("version", "1")), meta.get("description", ""), meta.get("when", ""), body)
    return out


# ── Generated skills ─────────────────────────────────────────────────────────

def _label(event_type: str) -> str:
    return EVENT_TYPES.get(event_type, {}).get("label", event_type)


def event_playbook_body() -> str:
    """The reliable event effects, rebuilt from the event studies (no hand-written beliefs)."""
    rows = db.rows(
        """SELECT type, instrument_id, horizon, n, edge, hit_rate, t_stat, q_value FROM event_impact
           WHERE reliable=1 AND horizon IN (10, 20, 40) ORDER BY type, instrument_id, horizon""")
    lines = [
        "Only these (event type x asset) effects passed the false-discovery correction (q <= 0.10), held in "
        "both halves of their history and have n >= 8. Every other event effect is indistinguishable from "
        "noise: do not use it as a reason to trade, however good its t-stat looks on its own.",
        "",
    ]
    if not rows:
        lines.append("Right now no event effect is reliable. Event history alone is not a reason to trade.")
    by_type: dict[str, list[dict]] = {}
    for row in rows:
        by_type.setdefault(row["type"], []).append(row)
    for event_type, effects in by_type.items():
        lines.append(f"## {_label(event_type)} ({event_type})")
        for e in effects:
            symbol = e["instrument_id"].split(":")[1].upper()
            research_only = " (index, not tradable)" if e["instrument_id"].startswith("index:") else ""
            lines.append(f"- {symbol}{research_only}, next {e['horizon']} sessions: edge {e['edge']:+.1%} vs normal, "
                         f"hit {e['hit_rate']:.0%}, n={e['n']}, t={e['t_stat']:+.1f}, q={e['q_value']:.3f}")
        lines.append("")
    active = [e for e in event_study.recent_events(10) if e["type"] in by_type]
    lines.append("## Active in the last 10 days")
    if active:
        for e in active[:15]:
            target = f" on {e['instrument_id']}" if e.get("instrument_id") else ""
            lines.append(f"- {e['date']}: {_label(e['type'])}{target}")
    else:
        lines.append("- none of the reliable event types fired recently")
    lines += ["", "How to use: an active reliable effect is one independent piece of evidence for the "
              "listed asset in the listed direction. Confirm the current price hasn't already moved by "
              "most of the edge since the event (asset_snapshot ret_5d), and check event_study for the "
              "full horizon profile before relying on it."]
    return "\n".join(lines)


GENERATED: dict[str, tuple[str, str, Callable[[], str]]] = {
    "event-playbook": (
        "Which event effects are statistically reliable right now, and which fired recently (rebuilt from data).",
        "Before using any event or macro news as a reason for a trade.",
        event_playbook_body,
    ),
}


def _generated(name: str) -> Skill:
    description, when, build = GENERATED[name]
    body = build()
    version = "g" + hashlib.sha1(body.encode()).hexdigest()[:8]
    return Skill(name, version, description, when, body)


# ── Public API ───────────────────────────────────────────────────────────────

def catalog() -> list[dict]:
    """Names, descriptions and trigger hints (no bodies; generated skills are not built here)."""
    items = [{"name": s.name, "description": s.description, "when": s.when, "version": s.version}
             for s in _file_skills().values()]
    items += [{"name": name, "description": d, "when": w, "version": "generated"} for name, (d, w, _) in GENERATED.items()]
    return sorted(items, key=lambda s: s["name"])


def get(name: str) -> Skill:
    if name in GENERATED:
        return _generated(name)
    skills = _file_skills()
    if name not in skills:
        raise KeyError(f"Unknown skill '{name}'. Available: {', '.join(s['name'] for s in catalog())}")
    return skills[name]


def prompt_section() -> str:
    lines = ["Skills: step-by-step playbooks. Load one with load_skill before the task it covers, and follow it."]
    lines += [f"- {s['name']}: {s['description']} Use when: {s['when']}" for s in catalog()]
    return "\n".join(lines)


def loaded_in(history: list[dict]) -> list[str]:
    """`name@version` of every skill successfully loaded in this conversation, in load order."""
    calls = {c["id"]: c for m in history if m.get("role") == "assistant" for c in m.get("tool_calls") or []
             if c.get("name") == "load_skill"}
    tags: list[str] = []
    for message in history:
        if message.get("role") != "tool":
            continue
        for result in message.get("results", []):
            if result.get("id") not in calls or result.get("is_error"):
                continue
            try:
                tag = json.loads(result["content"]).get("skill")
            except (ValueError, AttributeError):
                continue
            if tag and tag not in tags:
                tags.append(tag)
    return tags
