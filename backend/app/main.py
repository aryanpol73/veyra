"""ARGUS API. Phase 0: health + competitor CRUD. Later phases add cycle/signals/hypotheses/eval/chat."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import cycle, llm
from app.config import get_settings
from app.db.models import AgentRun, Competitor, Hypothesis, Signal, Source
from app.db.seed import sources_for
from app.db.session import get_db, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    sched = None
    s = get_settings()
    if s.scheduler_enabled:
        from apscheduler.schedulers.background import BackgroundScheduler

        sched = BackgroundScheduler()
        sched.add_job(cycle.start_cycle_async, "interval", minutes=s.cycle_interval_min, id="cycle")
        sched.start()
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(title="ARGUS", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- schemas ----------
class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source_type: str
    url: str
    active: bool
    last_checked_at: datetime | None
    last_status: str | None


class CompetitorIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    domain: str = Field(min_length=3)
    pricing_url: str | None = None
    product_urls: list[str] = []
    careers_provider: str | None = Field(default=None, pattern="^(greenhouse|lever)$")
    careers_token: str | None = None
    news_query: str | None = None
    feed_urls: list[str] = []
    notes: str | None = None


class CompetitorOut(CompetitorIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    sources: list[SourceOut] = []


# ---------- health ----------
@app.get("/health")
def health(llm_check: bool = False, db: Session = Depends(get_db)):
    s = get_settings()
    db.execute(text("SELECT 1"))
    out = {
        "status": "ok",
        "db": "ok",
        "llm": {
            "provider": s.llm_provider,
            "base_url": s.resolved_base_url,
            "strong": s.model_strong,
            "fast": s.model_fast,
            "configured": s.llm_configured,
        },
        "counts": {
            "competitors": db.scalar(select(func.count(Competitor.id))),
            "signals": db.scalar(select(func.count(Signal.id))),
            "hypotheses": db.scalar(select(func.count(Hypothesis.id))),
            "agent_runs": db.scalar(select(func.count(AgentRun.id))),
        },
    }
    if llm_check:
        out["llm"]["ping"] = llm.ping()
    return out


# ---------- competitors ----------
@app.get("/competitors", response_model=list[CompetitorOut])
def list_competitors(db: Session = Depends(get_db)):
    return db.scalars(select(Competitor).order_by(Competitor.name)).all()


@app.get("/competitors/{cid}", response_model=CompetitorOut)
def get_competitor(cid: int, db: Session = Depends(get_db)):
    c = db.get(Competitor, cid)
    if not c:
        raise HTTPException(404, "competitor not found")
    return c


@app.post("/competitors", response_model=CompetitorOut, status_code=201)
def create_competitor(body: CompetitorIn, db: Session = Depends(get_db)):
    if db.scalar(select(Competitor).where(Competitor.name == body.name)):
        raise HTTPException(409, "competitor with that name exists")
    c = Competitor(**body.model_dump())
    c.sources = sources_for(c)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@app.put("/competitors/{cid}", response_model=CompetitorOut)
def update_competitor(cid: int, body: CompetitorIn, db: Session = Depends(get_db)):
    c = db.get(Competitor, cid)
    if not c:
        raise HTTPException(404, "competitor not found")
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    # rebuild derived sources; snapshots for unchanged URLs are kept by re-pointing
    old = {(s.source_type, s.url): s for s in c.sources}
    new_sources = []
    for s in sources_for(c):
        new_sources.append(old.get((s.source_type, s.url), s))
    c.sources = new_sources
    db.commit()
    db.refresh(c)
    return c


@app.delete("/competitors/{cid}", status_code=204)
def delete_competitor(cid: int, db: Session = Depends(get_db)):
    c = db.get(Competitor, cid)
    if not c:
        raise HTTPException(404, "competitor not found")
    db.delete(c)
    db.commit()


@app.get("/sources", response_model=list[SourceOut])
def list_sources(competitor_id: int | None = None, db: Session = Depends(get_db)):
    q = select(Source)
    if competitor_id:
        q = q.where(Source.competitor_id == competitor_id)
    return db.scalars(q).all()


# ---------- cycle ----------
class CycleIn(BaseModel):
    competitor_ids: list[int] | None = None


@app.post("/cycle/run", status_code=202)
def run_cycle(body: CycleIn | None = None):
    started = cycle.start_cycle_async(body.competitor_ids if body else None)
    if not started:
        raise HTTPException(409, "a cycle is already running")
    return {"started": True}


@app.get("/cycle/status")
def cycle_status():
    return cycle.STATUS


# ---------- signals ----------
class SignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    competitor_id: int
    competitor: str | None = None
    source_id: int | None
    type: str
    category: str
    summary: str
    old_value: str | None
    new_value: str | None
    evidence_url: str
    observed_at: datetime
    detected_at: datetime
    origin_group: str
    event_confidence: float
    priority: str
    raw: dict
    synthetic: bool
    replay: bool


PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@app.get("/signals", response_model=list[SignalOut])
def list_signals(
    competitor: int | None = None,
    category: str | None = None,
    priority: str | None = None,
    type: str | None = None,
    since: datetime | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    q = select(Signal, Competitor.name).join(Competitor, Competitor.id == Signal.competitor_id)
    if competitor:
        q = q.where(Signal.competitor_id == competitor)
    if category:
        q = q.where(Signal.category == category)
    if priority:
        q = q.where(Signal.priority.in_(priority.split(",")))
    if type:
        q = q.where(Signal.type == type)
    if since:
        q = q.where(Signal.observed_at >= since)
    rows = db.execute(q.order_by(Signal.observed_at.desc()).limit(min(limit, 1000))).all()
    out = []
    for sig, name in rows:
        o = SignalOut.model_validate(sig)
        o.competitor = name
        out.append(o)
    return out


@app.get("/signals/stats")
def signal_stats(db: Session = Depends(get_db)):
    rows = db.execute(select(Signal.category, Signal.priority, func.count()).group_by(Signal.category, Signal.priority)).all()
    return [{"category": c, "priority": p, "count": n} for c, p, n in rows]
