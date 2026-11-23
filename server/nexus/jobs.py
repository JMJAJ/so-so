"""Named jobs (tracked in the `jobs` table) and the in-process scheduler."""

from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import config, data, db, live, nlp, paper, recommendations, snapshot, universe
from .ingest import events, gdelt, macro, news, prices, wire
from .research import backtest, event_study, replay, scan, simulate

_running: set[str] = set()
_progress: dict[str, str] = {}
_lock = threading.Lock()
_scheduler = None


def _focus_ids() -> list[str]:
    ids = {row["instrument_id"] for row in db.rows("SELECT instrument_id FROM positions")}
    ids |= {row["instrument_id"] for row in db.rows("SELECT instrument_id FROM recommendations WHERE status='open'")}
    try:
        ids |= {row["instrument_id"] for row in scan.ranked(limit=15)}
    except Exception:
        pass
    return sorted(ids)


_focus_cache: dict = {"at": 0.0, "ids": []}


def _focus_ids_cached() -> list[str]:
    """Focus list for the wire, recomputed at most every 10 minutes (ranking is not free)."""
    if time.time() - _focus_cache["at"] > 600:
        try:
            _focus_cache.update(at=time.time(), ids=_focus_ids())
        except Exception:
            _focus_cache["at"] = time.time()
    return _focus_cache["ids"]


def job_monitor(progress) -> dict:
    return {"paper": paper.monitor()}


def job_wire(progress) -> dict:
    progress("polling every wire feed")
    return wire.poll(_focus_ids(), force=True)


def job_news(progress) -> dict:
    progress("rss + yahoo + finnhub")
    result = news.update_news(_focus_ids())
    progress("gdelt headlines")
    result["gdelt"] = gdelt.fetch_doc_headlines("2h", 40)
    progress("classifying headlines")
    try:
        result["classified"] = nlp.classify_pending()
    except Exception as exc:  # no LLM configured is not fatal for ingestion
        result["classified"] = f"skipped: {exc}"
    return result


def job_daily(progress) -> dict:
    result = {"bars": prices.update_bars(progress=progress)}
    progress("macro")
    result["macro"] = macro.update_macro()
    progress("gdelt themes")
    result["themes"] = gdelt.update_themes(5)
    progress("events")
    result["events"] = events.update_events(progress, earnings=False)
    data.invalidate()
    progress("scoring recommendations")
    result["scored"] = recommendations.score_open()
    progress("post-mortems")
    try:
        result["postmortems"] = recommendations.write_postmortems()
    except Exception as exc:  # no LLM configured is not fatal for the daily refresh
        result["postmortems"] = f"skipped: {exc}"
    paper.monitor()
    paper.snapshot_equity()
    progress("forecasts")
    result["scan"] = len(scan.forecasts(refresh=True, progress=progress))
    return result


def job_research(progress) -> dict:
    result = {"earnings": events.detect_earnings(progress=progress)}
    data.invalidate()
    result["event_impact_rows"] = event_study.compute_all(progress)
    bt = backtest.run(progress=progress)
    result["models"] = {k: {"has_edge": v.get("has_edge"), "oos_ic": (v.get("walk_forward") or {}).get("ic")}
                        for k, v in bt["classes"].items()}
    result["replay"] = {k: replay.run(progress=progress).get(k) for k in ("calls", "hit_rate", "brier")}
    result["sim_check"] = (simulate.check(progress=progress).get("overall") or {}).get("in80")
    data.invalidate()
    scan.forecasts(refresh=True)
    return result


def job_sim_check(progress) -> dict:
    overall = simulate.check(progress=progress).get("overall") or {}
    return {k: overall.get(k) for k in ("n", "in80", "in50", "verdict")}


def job_analyst(progress) -> dict:
    from .agent import analyst

    progress("analyst investigating")
    return analyst.run(on_event=lambda e: e["type"] == "tool_call" and progress(f"tool {e['name']}"))


def job_news_backfill(progress) -> dict:
    """A year of Finnhub company news and three months of GDELT headlines, then dedupe and classify."""
    result = {"finnhub": news.backfill_finnhub(progress=progress),
              "gdelt": gdelt.backfill_doc_headlines(progress=progress)}
    progress("marking duplicate stories")
    result["duplicates"] = news.mark_duplicates(days=400)
    progress("classifying backfilled headlines")
    try:
        result["classified"] = nlp.classify_pending(limit=5000, days=400, deadline_s=60 * 60)
    except Exception as exc:  # no LLM configured is not fatal for ingestion
        result["classified"] = f"skipped: {exc}"
    return result


def job_gdelt_backfill(progress) -> dict:
    return gdelt.update_themes(config.get_int("gdelt_backfill_days"), progress, deadline_s=20 * 60)


def job_init(progress) -> dict:
    """First-run bootstrap: full history, events, studies, model validation."""
    result = {"bars": prices.update_bars(progress=progress)}
    data.invalidate()
    progress("macro")
    result["macro"] = macro.update_macro()
    progress("gdelt (last 30 days; the rest backfills in the background)")
    result["themes"] = gdelt.update_themes(30, progress)
    data.invalidate()
    result["events"] = events.update_events(progress, earnings=True)
    result["event_impact_rows"] = event_study.compute_all(progress)
    bt = backtest.run(progress=progress)
    result["models"] = {k: v.get("has_edge") for k, v in bt["classes"].items()}
    result["replay"] = replay.run(progress=progress).get("calls")
    data.invalidate()
    progress("news")
    result["news"] = news.update_news()
    paper.snapshot_equity()
    result["scan"] = len(scan.forecasts(refresh=True, progress=progress))
    return result


JOBS: dict[str, tuple[Callable, str]] = {
    "init": (job_init, "Full bootstrap: 10y prices, macro, events, event studies, backtest, replay"),
    "daily": (job_daily, "Daily bars, macro, events, score recommendations, forecasts"),
    "news": (job_news, "Fetch and classify headlines"),
    "wire": (job_wire, "Poll every breaking-news feed now (it also runs by itself about once a minute)"),
    "monitor": (job_monitor, "Fill pending orders, enforce stops/targets/expiry"),
    "research": (job_research, "Earnings history, event studies, walk-forward backtest, point-in-time replay"),
    "analyst": (job_analyst, "AI research run that writes recommendations"),
    "news_backfill": (job_news_backfill, "A year of company news + 3 months of GDELT headlines, deduped, classified"),
    "gdelt_backfill": (job_gdelt_backfill, "Backfill GDELT geopolitical history"),
    "sim_check": (job_sim_check, "Simulation honesty check: replay the price simulator on past dates"),
}


def run(name: str, progress: Callable[[str], None] | None = None) -> dict:
    if name not in JOBS:
        raise KeyError(f"Unknown job {name}")
    with _lock:
        if name in _running:
            raise RuntimeError(f"Job {name} is already running")
        _running.add(name)
    started = time.time()
    db.execute(
        """INSERT INTO jobs(name,last_started,last_status) VALUES(?,?,?)
           ON CONFLICT(name) DO UPDATE SET last_started=excluded.last_started, last_status='running'""",
        (name, db.now_iso(), "running"),
    )
    live.publish("job", name=name, status="running")

    def report(message: str) -> None:
        _progress[name] = message
        live.publish("progress", name=name, message=message)
        if progress:
            progress(message)

    try:
        result = JOBS[name][0](report)
        db.execute("UPDATE jobs SET last_finished=?, last_status='ok', last_error=NULL, last_summary=?, duration_ms=? WHERE name=?",
                   (db.now_iso(), db.dumps(result)[:4000], int((time.time() - started) * 1000), name))
        live.publish("job", name=name, status="ok")
        if name not in ("monitor", "wire"):
            snapshot.push_async(f"after {name}")
        return result
    except Exception as exc:
        db.execute("UPDATE jobs SET last_finished=?, last_status='error', last_error=?, duration_ms=? WHERE name=?",
                   (db.now_iso(), f"{exc}\n{traceback.format_exc()[-1500:]}", int((time.time() - started) * 1000), name))
        db.log("error", "job", f"{name}: {exc}")
        live.publish("job", name=name, status="error")
        raise
    finally:
        with _lock:
            _running.discard(name)
        _progress.pop(name, None)


def run_async(name: str) -> None:
    if name not in JOBS:
        raise KeyError(f"Unknown job {name}")
    if name in _running:
        raise RuntimeError(f"Job {name} is already running")

    def target() -> None:
        try:
            run(name)
        except Exception:
            pass  # recorded in the jobs table

    threading.Thread(target=target, daemon=True, name=f"job-{name}").start()


def status() -> list[dict]:
    stored = {row["name"]: row for row in db.rows("SELECT * FROM jobs")}
    next_runs = {}
    if _scheduler:
        for job in _scheduler.get_jobs():
            next_runs[job.id] = job.next_run_time.isoformat() if job.next_run_time else None
    return [{
        "name": name, "description": description, "running": name in _running, "progress": _progress.get(name),
        "next_run": next_runs.get(name), **{k: v for k, v in (stored.get(name) or {}).items() if k != "name"},
    } for name, (_, description) in JOBS.items()]


_has_data: dict[str, bool] = {}


def has_data() -> bool:
    """Whether history has been downloaded. Polled constantly, and once true it stays true, so
    the (slow) count over every bar runs only until the first bootstrap finishes."""
    if _has_data.get(db.DB_PATH):
        return True
    row = db.one("SELECT COUNT(DISTINCT instrument_id) c FROM bars")
    result = bool(row and row["c"] >= len(universe.INSTRUMENTS) // 2)
    if result:
        _has_data[db.DB_PATH] = True
    return result


def start_scheduler() -> None:
    global _scheduler
    if _scheduler or not config.get_bool("scheduler_enabled"):
        return
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    def safe(name: str):
        def fire() -> None:
            if name == "analyst" and not _llm_ready():
                return
            if name != "init" and not has_data():
                return
            try:
                run(name)
            except Exception:
                pass
        return fire

    scheduler = BackgroundScheduler(timezone="UTC", job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600})
    soon = datetime.now(timezone.utc) + timedelta(seconds=90)
    scheduler.add_job(safe("monitor"), IntervalTrigger(minutes=5), id="monitor", next_run_time=soon)
    scheduler.add_job(safe("news"), IntervalTrigger(minutes=max(2, config.get_int("news_interval_min"))), id="news",
                      next_run_time=soon)
    scheduler.add_job(safe("daily"), CronTrigger(hour=21, minute=45, timezone="UTC"), id="daily")
    scheduler.add_job(safe("analyst"), CronTrigger(hour=22, minute=30, timezone="UTC"), id="analyst")
    scheduler.add_job(safe("research"), CronTrigger(day_of_week="sat", hour=6, timezone="UTC"), id="research")
    scheduler.add_job(safe("gdelt_backfill"), IntervalTrigger(hours=2), id="gdelt_backfill",
                      next_run_time=soon + timedelta(minutes=10))
    scheduler.start()
    _scheduler = scheduler
    wire.start(_focus_ids_cached)


def stop_scheduler() -> None:
    global _scheduler
    wire.stop()
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def _llm_ready() -> bool:
    provider = config.get("llm_provider")
    # Anthropic: the SDK can also resolve an `ant auth login` profile, so a missing key isn't conclusive.
    if provider in ("openai", "openrouter"):
        return bool(config.secret(f"{provider}_api_key"))
    return True
