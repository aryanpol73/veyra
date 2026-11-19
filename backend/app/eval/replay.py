"""Replay mode: run the SAME detectors + agent graph over the frozen dataset, stepping `as_of` through time.

Leakage safety (asserted in tests/test_replay.py):
  * ReplayStore only yields captures with observed_at <= as_of;
  * every agent tool filters by as_of, fetch_url / web_search are disabled when as_of is set;
  * the network fetcher is replaced by one that raises, so any accidental live call fails loudly;
  * replay writes to its own SQLite file, never the live database.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import llm
from app.collectors import base as collectors_base
from app.collectors.base import RawObservation
from app.config import get_settings
from app.db.models import Competitor, Signal, Source
from app.db.sources import sources_for
from app.eval.companies import BACKTEST_COMPANIES as COMPETITORS
from app.db.session import audit_into, init_db, session_scope
from app.detect import detectors as det
from app.detect.normalize import persist
from app.detect.snapshot import last_snapshot, store
from app.eval.dataset import REPLAY_DIR, slug, source_key

log = logging.getLogger("veyra.replay")

# Contamination control: names + products that identify each company (masked mode only).
ALIASES: dict[str, dict[str, str]] = {
    "Vercel": {"Vercel": "CompanyA", "vercel.com": "companya.example", "Next.js": "FrameworkA", "v0": "ProductA1",
               "Turbopack": "ProductA2", "Turborepo": "ProductA3"},
    "Figma": {"Figma": "CompanyB", "figma.com": "companyb.example", "FigJam": "ProductB1", "Figma Make": "ProductB2",
              "Dylan Field": "CEO-B"},
    "Airtable": {"Airtable": "CompanyC", "airtable.com": "companyc.example", "Howie Liu": "CEO-C"},
}


class NoNetworkFetcher:
    network_calls = 0

    def get(self, url: str, **_):  # noqa: D401
        raise AssertionError(f"LEAKAGE GUARD: live fetch attempted in replay: {url}")


@dataclass
class Capture:
    url: str
    source_type: str
    observed_at: datetime
    content_text: str
    content_hash: str
    meta: dict
    wayback_url: str


class ReplayStore:
    def __init__(self, root: Path = REPLAY_DIR):
        self.root = root

    def captures(self, competitor: str, url: str) -> list[Capture]:
        folder = self.root / slug(competitor) / source_key(url)
        out = []
        for p in sorted(folder.glob("*.json")) if folder.exists() else []:
            d = json.loads(p.read_text("utf-8"))
            out.append(Capture(d["url"], d["source_type"], datetime.fromisoformat(d["observed_at"]), d["content_text"],
                               d["content_hash"], d.get("meta", {}), d["wayback_url"]))
        return sorted(out, key=lambda c: c.observed_at)

    def between(self, competitor: str, url: str, after: datetime | None, as_of: datetime) -> list[Capture]:
        return [c for c in self.captures(competitor, url) if c.observed_at <= as_of and (after is None or c.observed_at > after)]


def _aware(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def setup_replay_db() -> None:
    """Fresh schema + seeded competitors. Only sources that HAVE frozen history stay active."""
    init_db()
    store_ = ReplayStore()
    with session_scope() as db:
        if db.scalar(select(func.count(Competitor.id))):
            return
        for data in COMPETITORS:
            c = Competitor(**data)
            c.sources = sources_for(c)
            for s in c.sources:
                s.active = s.source_type in ("page", "news") and bool(store_.captures(c.name, s.url))
            db.add(c)


def ingest_step(db: Session, as_of: datetime, store_: ReplayStore, mode: str = "none") -> dict[int, list[int]]:
    """Feed every frozen capture with prev < observed_at <= as_of through snapshot + detectors.
    In masked mode the classifier prompts are masked too (not just the agents)."""
    before = db.scalar(select(func.max(Signal.id))) or 0
    for comp in db.scalars(select(Competitor)).all():
        llm.set_mask(ALIASES.get(comp.name) if mode == "masked" else None)
        for src in [s for s in comp.sources if s.active]:
            prev = last_snapshot(db, src.id, as_of)
            for cap in store_.between(comp.name, src.url, _aware(prev.observed_at) if prev else None, as_of):
                assert cap.observed_at <= as_of, "leakage: capture after as_of"
                obs = RawObservation(comp.id, src.id, src.source_type, src.url, cap.observed_at, cap.observed_at,
                                     cap.content_text, cap.content_hash, {**cap.meta, "wayback_url": cap.wayback_url})
                prev = last_snapshot(db, src.id, as_of)
                cur, changed = store(db, obs, prev)
                if changed and src.source_type == "page":
                    drafts = det.detect_page(db, comp, src, obs, prev, cur, allow_wayback=False)
                    for d in drafts:
                        d.raw["previous_version_url"] = (prev.meta or {}).get("wayback_url") if prev else None
                        d.raw["current_version_url"] = cap.wayback_url
                        d.evidence_url = cap.wayback_url  # evidence = the archived capture, not today's page
                    persist(db, comp.id, src.id, drafts, replay=True, detected_at=as_of)
                elif changed and src.source_type == "news":
                    det.detect_news(db, comp, src, obs, prev, cur, replay=True, detected_at=as_of)
    llm.set_mask(None)
    db.flush()
    new: dict[int, list[int]] = {}
    for sid, cid in db.execute(select(Signal.id, Signal.competitor_id).where(Signal.id > before)).all():
        new.setdefault(cid, []).append(sid)
    return new


def monthly_steps(start: datetime, end: datetime) -> list[datetime]:
    out, d = [], start
    while d <= end:
        out.append(d)
        d = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
    if out[-1] < end:
        out.append(end)
    return out


def run_replay(steps: list[datetime], *, mode: str = "masked", agents: bool = True, progress=print) -> list[dict]:
    """Run inside a process whose DB_URL already points at a fresh replay database."""
    from app.agents.graph import run_agents_for  # after DB_URL is set

    s = get_settings()
    # lighter per-step budgets so a 7-step x 3-company replay fits the Groq free tier (8k tokens/min)
    s.max_investigations_per_cycle, s.max_skeptic_per_cycle, s.strategist_max_signals = 1, 1, 25
    collectors_base._fetcher = NoNetworkFetcher()  # type: ignore[assignment]
    setup_replay_db()
    store_ = ReplayStore()
    logs = []
    for as_of in steps:
        with session_scope() as db, audit_into(db):
            new = ingest_step(db, as_of, store_, mode)
            db.commit()
            step = {"as_of": as_of.isoformat(), "new_signals": {k: len(v) for k, v in new.items()}, "agents": []}
            if agents and s.llm_configured:
                for comp in db.scalars(select(Competitor)).all():
                    if not new.get(comp.id):
                        continue  # nothing new this month: don't spend tokens
                    llm.set_mask(ALIASES.get(comp.name) if mode == "masked" else None)
                    try:
                        r = run_agents_for(db, comp, new_signal_ids=new[comp.id], as_of=as_of)
                    finally:
                        llm.set_mask(None)
                    db.commit()
                    step["agents"].append({"competitor": comp.name, "tokens": r.get("tokens_used"), "log": r.get("log")})
            progress(f"[{mode}] {as_of:%Y-%m-%d}: new signals {step['new_signals']}, "
                     f"agent tokens {sum((a['tokens'] or 0) for a in step['agents'])}")
            logs.append(step)
    return logs
