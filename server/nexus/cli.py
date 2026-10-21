"""Command line: `python -m nexus <command>` (run from the server/ directory).

Every command accepts --json for machine-readable output, so scripts and Claude
Code can drive the same tools the in-app AI uses.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import db


JOB_ALIASES = {"update": "daily", "news-backfill": "news_backfill"}

def _print_json(value) -> None:
    from .api import clean

    print(json.dumps(clean(value), indent=2, default=str))


def _pct(value, digits: int = 1) -> str:
    return "—" if value is None else f"{value * 100:+.{digits}f}%"


def _table(rows: list[dict], columns: list[tuple[str, str]]) -> None:
    if not rows:
        print("(none)")
        return
    rendered = [[str(row.get(key, "")) if not callable(key) else key(row) for key, _ in columns] for row in rows]
    widths = [max(len(title), *(len(r[i]) for r in rendered)) for i, (_, title) in enumerate(columns)]
    print("  ".join(title.ljust(widths[i]) for i, (_, title) in enumerate(columns)))
    print("  ".join("-" * w for w in widths))
    for r in rendered:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(r)))


def _progress(message: str) -> None:
    print(f"  · {message}", file=sys.stderr, flush=True)


def _stream_event(event: dict) -> None:
    if event["type"] == "text":
        print(event["text"], end="", flush=True)
    elif event["type"] == "tool_call":
        args = json.dumps(event["input"])[:120]
        print(f"\n  ↳ {event['name']}({args})", file=sys.stderr, flush=True)
    elif event["type"] == "tool_result" and event["is_error"]:
        print(f"    ✗ {event['preview'][:200]}", file=sys.stderr, flush=True)
    elif event["type"] == "error":
        print(f"\n[error] {event['message']}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    parser = argparse.ArgumentParser(prog="nexus", description="NEXUS research terminal CLI")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="download history and build all research (first run, ~10-20 min)")
    for name in ("update", "news", "news-backfill", "research", "monitor"):
        sub.add_parser(name, help=f"run the '{JOB_ALIASES.get(name, name)}' job now")
    p = sub.add_parser("scan", help="rank the universe by today's forecast/evidence")
    p.add_argument("--class", dest="asset_class")
    p.add_argument("--direction", default="both", choices=["long", "short", "both"])
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--refresh", action="store_true")
    p = sub.add_parser("asset", help="evidence snapshot for one instrument")
    p.add_argument("instrument")
    p = sub.add_parser("event", help="event study: what an asset did after an event type")
    p.add_argument("event_type")
    p.add_argument("instrument")
    p = sub.add_parser("recommend", help="run the AI analyst (writes recommendations)")
    p.add_argument("--focus", help="e.g. 'semiconductors' or 'NVDA'")
    p.add_argument("--max", type=int, dest="max_recs")
    p = sub.add_parser("ask", help="ask the AI a question (uses the same tools as the app chat)")
    p.add_argument("question", nargs="+")
    p.add_argument("--conv", help="continue a conversation id")
    p = sub.add_parser("recs", help="list recommendations")
    p.add_argument("--status", default="open", choices=["open", "closed", "cancelled", "all"])
    p = sub.add_parser("why", help="show a recommendation's thesis and evidence")
    p.add_argument("rec_id")
    sub.add_parser("portfolio", help="paper account")
    sub.add_parser("report", help="track record: is the AI actually right?")
    p = sub.add_parser("backtest", help="walk-forward validation results (use --run to recompute)")
    p.add_argument("--run", action="store_true")
    p = sub.add_parser("replay", help="point-in-time replay of the evidence engine (use --run to recompute)")
    p.add_argument("--run", action="store_true")
    sub.add_parser("regime", help="current macro regime")
    sub.add_parser("jobs", help="job status")
    p = sub.add_parser("serve", help="start the API server")
    p.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    db.init_db()
    cmd = args.command

    if cmd in ("init", "update", "news", "news-backfill", "research", "monitor"):
        from . import jobs

        name = JOB_ALIASES.get(cmd, cmd)
        result = jobs.run(name, progress=_progress)
        _print_json(result)
        return 0

    if cmd == "scan":
        from .research import scan

        scan.forecasts(refresh=args.refresh, progress=_progress if args.refresh else None)
        rows = scan.ranked(args.asset_class, args.direction, args.limit)
        if args.json:
            _print_json(rows)
        else:
            _table(rows, [
                ("symbol", "SYMBOL"), ("asset_class", "CLASS"),
                (lambda r: f"{r['price']:.4g}", "PRICE"),
                (lambda r: _pct(r.get("expected_return")), "E[20d]"),
                (lambda r: f"{(r.get('prob_up') or 0):.0%}", "P(up)"),
                (lambda r: "yes" if r.get("model_has_edge") else "no", "EDGE"),
                (lambda r: f"{(r['signals'].get('event') or 0):+.2f}", "EVENT"),
                (lambda r: f"{(r['signals'].get('analog') or 0):+.2f}", "ANALOG"),
                (lambda r: f"{r.get('news_flow') or 0:+d}", "NEWS"),
                (lambda r: ",".join(r.get("recent_events") or [])[:40], "RECENT EVENTS"),
            ])
        return 0

    from .agent import tools

    if cmd == "asset":
        result = {name: json.loads(tools.call(name, {"instrument": args.instrument})[0])
                  for name in ("asset_snapshot", "event_effects", "analogs", "correlations", "recent_news")}
        _print_json(result)
        return 0

    if cmd == "event":
        _print_json(json.loads(tools.call("event_study", {"event_type": args.event_type, "instrument": args.instrument})[0]))
        return 0

    if cmd == "regime":
        _print_json(json.loads(tools.call("macro_regime", {})[0]))
        return 0

    if cmd == "recommend":
        from .agent import analyst

        result = analyst.run(focus=args.focus, max_recs=args.max_recs, on_event=None if args.json else _stream_event)
        print()
        if args.json:
            _print_json(result)
        else:
            print(f"\nRun {result['run_id']}: {result['recommendations']} new recommendation(s). See: python -m nexus recs")
        return 0

    if cmd == "ask":
        from .agent import chat

        result = chat.send(args.conv, " ".join(args.question), on_event=None if args.json else _stream_event)
        if args.json:
            _print_json(result)
        else:
            print(f"\n\n(conversation {result['conversation_id']} — continue with --conv {result['conversation_id']})")
        return 0

    from . import paper, recommendations

    if cmd == "recs":
        rows = recommendations.list_recs(None if args.status == "all" else args.status, 200)
        if args.json:
            _print_json(rows)
        else:
            _table(rows, [
                ("id", "ID"), ("symbol", "SYMBOL"), ("direction", "DIR"), ("horizon_days", "H"),
                (lambda r: f"{r['entry_price']:.4g}", "ENTRY"), (lambda r: f"{r['stop']:.4g}", "STOP"),
                (lambda r: f"{r['target']:.4g}", "TARGET"), (lambda r: f"{r['probability']:.0%}", "P"),
                ("status", "STATUS"),
                (lambda r: _pct(r["realized_return"] if r["status"] == "closed" else r.get("mark_return")), "RETURN"),
                (lambda r: r["created_at"][:10], "DATE"),
            ])
        return 0

    if cmd == "why":
        rec = recommendations.get(args.rec_id)
        if args.json:
            _print_json(rec)
        else:
            print(f"{rec['direction'].upper()} {rec['symbol']} — {rec['horizon_days']} sessions, p={rec['probability']:.0%} "
                  f"({rec['confidence']})\nentry {rec['entry_price']:.4g}  stop {rec['stop']:.4g}  target {rec['target']:.4g}\n")
            print(rec["thesis"], "\n")
            for item in rec["evidence"]:
                print(f"  [{item.get('type')}] {item.get('summary')}")
            if rec.get("invalidation"):
                print(f"\nInvalidation: {rec['invalidation']}")
            if rec["status"] == "closed":
                print(f"\nResult: {_pct(rec['realized_return'])} ({rec['exit_reason']}), excess {_pct(rec['excess_return'])}")
        return 0

    if cmd == "portfolio":
        state = paper.portfolio()
        if args.json:
            _print_json(state)
        else:
            print(f"Equity {state['equity']:,.2f} ({state['return_pct']:+.2f}%)  exposure {state['exposure_pct']:.0f}%  "
                  f"realized {state['realized']:+,.2f}  open P&L {state['unrealized']:+,.2f}\n")
            _table(state["positions"], [
                ("symbol", "SYMBOL"), ("side", "SIDE"), ("status", "STATUS"), ("quantity", "QTY"),
                (lambda r: f"{r['entry_price'] or 0:.4g}", "ENTRY"), (lambda r: f"{r['current_price'] or 0:.4g}", "MARK"),
                (lambda r: f"{r['pnl']:+,.2f}", "P&L"), (lambda r: f"{r['stop']:.4g}", "STOP"),
                (lambda r: f"{r['target'] or 0:.4g}", "TARGET"),
            ])
        return 0

    if cmd == "report":
        record = recommendations.track_record()
        if args.json:
            _print_json(record)
        else:
            print(recommendations.lessons())
        return 0

    if cmd == "backtest":
        from .research import backtest

        if args.run:
            backtest.run(progress=_progress)
        rows = backtest.summary()
        if args.json:
            _print_json(rows)
        else:
            for row in rows:
                wf = row.get("walk_forward") or {}
                print(f"\n{row['asset_class'].upper()}: edge={'YES' if row['has_edge'] else 'no'}  "
                      f"OOS IC {wf.get('ic', 0):+.3f} (t={wf.get('t_stat', 0):.1f}, n={wf.get('n', 0)})  "
                      f"top-bottom quintile {_pct(wf.get('long_short'))}  {row.get('reason') or ''}")
                for name, stats in (row.get("signals") or {}).items():
                    print(f"   {name:<9} IC {stats['ic']:+.3f}  t={stats['t_stat']:+.1f}  n={stats['n']}")
        return 0

    if cmd == "replay":
        from .research import probability, replay

        result = replay.run(progress=_progress) if args.run else replay.summary()
        if args.json:
            _print_json(result)
        elif not result.get("calls"):
            print("No replay yet. Run: python -m nexus replay --run")
        else:
            print(f"{result['calls']} calls {result['period'][0]}..{result['period'][1]}: hit rate {result['hit_rate']:.0%}, "
                  f"avg {_pct(result['avg_return'])} (t={result['t_stat']:.1f}), stated p {result['avg_probability']:.0%}, "
                  f"Brier {result['brier']:.3f}")
            for b in result["calibration"]:
                print(f"   p {b['bucket']}: n={b['n']:<4} stated {b['stated']:.0%}  realized {b['realized']:.0%}")
            for row in result["by_event_type"][:12]:
                print(f"   {row['event_type']:<22} n={row['n']:<4} hit {row['hit_rate']:.0%}  avg {_pct(row['avg_return'])}")
            k, basis = probability.calibration_factor()
            print(f"calibration k={k:.2f} ({basis})")
        return 0

    if cmd == "jobs":
        from . import jobs

        _print_json(jobs.status())
        return 0

    if cmd == "serve":
        import uvicorn

        uvicorn.run("nexus.api:app", host="127.0.0.1", port=args.port)
        return 0
    return 1
