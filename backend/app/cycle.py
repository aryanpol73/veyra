"""One monitoring cycle: collect every active source -> snapshot -> detect -> persist signals.

Runs in a background thread (POST /cycle/run). Each source is isolated: one failing site never
stops the cycle. Phase 2 appends the agent graph (strategist -> investigator -> skeptic -> judge).
"""
from __future__ import annotations

import logging
import threading
import traceback
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from app.collectors.base import FetchError, RobotsBlocked, fetcher
from app.collectors.registry import COLLECTORS
from app.config import get_settings
from app.db.models import Competitor, Signal, Source
from app.db.session import audit_into, log_agent_run, session_scope
from app.detect import detectors as det
from app.detect.normalize import persist
from app.detect.snapshot import last_snapshot, store

log = logging.getLogger("veyra.cycle")

_lock = threading.Lock()
STATUS: dict[str, Any] = {"running": False, "started_at": None, "finished_at": None, "current": None, "mode": None,
                          "sources": [], "signals_created": 0, "errors": 0, "agents": [], "run_id": None}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def run_source(db, comp: Competitor, src: Source) -> dict:
    prev = last_snapshot(db, src.id)
    collector = COLLECTORS[src.source_type]
    try:
        observations = collector.collect(comp, src)
    except RobotsBlocked as e:
        src.last_status = "robots-blocked"
        return {"source_id": src.id, "url": src.url, "status": "robots-blocked", "error": str(e), "signals": 0}
    except (FetchError, ValueError) as e:
        created = persist(db, comp.id, src.id, det.page_gone(comp, src, prev, str(e), _now())) if src.source_type == "page" else []
        src.last_status = f"error: {str(e)[:150]}"
        return {"source_id": src.id, "url": src.url, "status": "error", "error": str(e)[:300], "signals": len(created)}
    created = 0
    for obs in observations:
        cur, changed = store(db, obs, prev)
        if not changed and prev is not None:
            continue
        if src.source_type == "page":
            created += len(persist(db, comp.id, src.id, det.detect_page(db, comp, src, obs, prev, cur)))
        elif src.source_type == "jobs":
            created += len(persist(db, comp.id, src.id, det.detect_jobs(db, comp, src, obs, prev, cur)))
        elif src.source_type == "news":
            created += det.detect_news(db, comp, src, obs, prev, cur)
        elif obs.meta.get("kind") == "ct":
            created += len(persist(db, comp.id, src.id, det.detect_ct(db, comp, src, obs, prev, cur)))
        else:
            created += len(persist(db, comp.id, src.id, det.detect_sitemap(db, comp, src, obs, prev, cur)))
    src.last_status = "ok"
    return {"source_id": src.id, "url": src.url, "status": "ok", "signals": created,
            "changed": bool(observations) and (prev is None or prev.content_hash != observations[-1].content_hash)}


def _agents(db, comps: list[Competitor], new_ids: dict[int, list[int]]) -> None:
    """Agent graph per competitor (skipped without an LLM). Each competitor commits separately."""
    from app.agents.graph import run_agents_for
    from app.agents.tools import CycleBudget

    if not get_settings().llm_configured:
        STATUS["agents"].append({"skipped": "no LLM configured (add GROQ_API_KEY, MISTRAL_API_KEY or GEMINI_API_KEY)"})
        return
    budget = CycleBudget(get_settings().cycle_max_fetches)
    for comp in comps:
        STATUS["current"] = f"{comp.name}: agents (strategist -> investigator -> skeptic -> judge)"
        try:
            r = run_agents_for(db, comp, new_signal_ids=new_ids.get(comp.id, []), cycle_budget=budget)
            db.commit()
        except Exception as e:  # noqa: BLE001
            db.rollback()
            log.exception("agents failed for %s", comp.name)
            r = {"error": f"{type(e).__name__}: {e}"[:300]}
        if r.get("alerts"):  # push only after the alert rows are committed
            try:
                from app.push import notify_alerts

                r["push"] = notify_alerts(db, r["alerts"])
                db.commit()
            except Exception as e:  # noqa: BLE001 - a push failure must never fail the cycle
                db.rollback()
                log.warning("push delivery failed: %s", e)
        STATUS["agents"].append({"competitor": comp.name, **r})


def run_cycle(competitor_ids: list[int] | None = None, *, collect: bool = True, agents: bool = True) -> dict:
    started = _now()
    STATUS.update(running=True, started_at=started.isoformat(), finished_at=None, sources=[], signals_created=0,
                  errors=0, agents=[], mode="collect+agents" if collect and agents else "collect" if collect else "agents")
    calls_before = fetcher().network_calls
    try:
        with session_scope() as db, audit_into(db):
            q = select(Competitor)
            if competitor_ids:
                q = q.where(Competitor.id.in_(competitor_ids))
            comps = db.scalars(q).all()
            max_before = db.scalar(select(func.max(Signal.id))) or 0
            for comp in comps if collect else []:
                for src in [s for s in comp.sources if s.active]:
                    STATUS["current"] = f"{comp.name}: {src.source_type} {src.url}"
                    try:
                        with db.begin_nested():  # savepoint: a crash in one source rolls back only that source
                            res = run_source(db, comp, src)
                    except Exception as e:  # noqa: BLE001
                        log.exception("source %s failed", src.url)
                        res = {"source_id": src.id, "url": src.url, "status": "crash", "error": f"{type(e).__name__}: {e}"[:300],
                               "trace": traceback.format_exc()[-1500:], "signals": 0}
                        src.last_status = f"crash: {type(e).__name__}"
                    src.last_checked_at = _now()
                    res["competitor"] = comp.name
                    res["source_type"] = src.source_type
                    STATUS["sources"].append(res)
                    STATUS["signals_created"] += res["signals"]
                    STATUS["errors"] += res["status"] not in ("ok",)
                    db.commit()
            new_ids: dict[int, list[int]] = {}
            for sid, cid in db.execute(select(Signal.id, Signal.competitor_id).where(Signal.id > max_before)).all():
                new_ids.setdefault(cid, []).append(sid)
            if agents:
                _agents(db, comps, new_ids)
    finally:
        summary = {k: STATUS[k] for k in ("signals_created", "errors")}
        summary["agents"] = STATUS["agents"]
        summary["network_calls"] = fetcher().network_calls - calls_before
        STATUS["run_id"] = log_agent_run("cycle", started, {"competitor_ids": competitor_ids},
                                         {**summary, "sources": STATUS["sources"]})
        STATUS.update(running=False, finished_at=_now().isoformat(), current=None)
    return dict(STATUS)


def start_cycle_async(competitor_ids: list[int] | None = None, *, collect: bool = True, agents: bool = True) -> bool:
    """Start a cycle in a background thread. False if one is already running."""
    if not _lock.acquire(blocking=False):
        return False

    def _run():
        try:
            run_cycle(competitor_ids, collect=collect, agents=agents)
        finally:
            _lock.release()

    STATUS["running"] = True
    threading.Thread(target=_run, name="veyra-cycle", daemon=True).start()
    return True
