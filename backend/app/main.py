"""Veyra API. Phase 0: health + competitor CRUD. Later phases add cycle/signals/hypotheses/eval/chat."""
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
from app.belief.engine import band_label
from app.db.models import (Alert, AgentRun, BeliefHistory, Competitor, Hypothesis, HypothesisEvidence, Investigation,
                           Prediction, Signal, SkepticChallenge, Source, UserFeedback)
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


app = FastAPI(title="Veyra", version="0.1.0", lifespan=lifespan)
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
    collect: bool = True  # fetch sources
    agents: bool = True  # then run strategist -> investigator -> skeptic -> judge


@app.post("/cycle/run", status_code=202)
def run_cycle(body: CycleIn | None = None):
    body = body or CycleIn()
    if not body.collect and not body.agents:
        raise HTTPException(422, "nothing to do: collect and agents are both false")
    started = cycle.start_cycle_async(body.competitor_ids, collect=body.collect, agents=body.agents)
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


# ---------- hypotheses ----------
def _hyp_summary(h: Hypothesis, name: str, n_for: int, n_against: int) -> dict:
    return {"id": h.id, "competitor_id": h.competitor_id, "competitor": name, "statement": h.statement,
            "category": h.category, "status": h.status, "confidence": h.confidence, "band": band_label(h.confidence),
            "prior": h.prior, "created_at": h.created_at, "updated_at": h.updated_at, "closed_at": h.closed_at,
            "evidence_for": n_for, "evidence_against": n_against, "replay": h.replay, "synthetic": h.synthetic,
            "score_label": "Uncalibrated heuristic score"}


@app.get("/hypotheses")
def list_hypotheses(competitor: int | None = None, status: str | None = None, db: Session = Depends(get_db)):
    q = select(Hypothesis, Competitor.name).join(Competitor, Competitor.id == Hypothesis.competitor_id)
    if competitor:
        q = q.where(Hypothesis.competitor_id == competitor)
    if status:
        q = q.where(Hypothesis.status.in_(status.split(",")))
    counts: dict[tuple[int, str], int] = {
        (hid, st): n for hid, st, n in db.execute(select(HypothesisEvidence.hypothesis_id, HypothesisEvidence.stance, func.count())
                                                  .group_by(HypothesisEvidence.hypothesis_id, HypothesisEvidence.stance)).all()}
    rows = db.execute(q.order_by(Hypothesis.confidence.desc())).all()
    return [_hyp_summary(h, n, counts.get((h.id, "supports"), 0), counts.get((h.id, "contradicts"), 0)) for h, n in rows]


@app.get("/hypotheses/{hid}")
def get_hypothesis(hid: int, db: Session = Depends(get_db)):
    h = db.get(Hypothesis, hid)
    if not h:
        raise HTTPException(404, "hypothesis not found")
    comp = db.get(Competitor, h.competitor_id)
    ev = db.execute(select(HypothesisEvidence, Signal).join(Signal, Signal.id == HypothesisEvidence.signal_id)
                    .where(HypothesisEvidence.hypothesis_id == hid).order_by(HypothesisEvidence.contribution.desc())).all()
    evidence = [{"id": he.id, "stance": he.stance, "relevance": he.relevance, "reliability": he.reliability,
                 "independence_weight": he.independence_weight, "contribution": he.contribution, "rationale": he.rationale,
                 "added_by": he.added_by, "signal": SignalOut.model_validate(s).model_dump()} for he, s in ev]
    n_for = sum(e["stance"] == "supports" for e in evidence)
    n_against = sum(e["stance"] == "contradicts" for e in evidence)
    out = _hyp_summary(h, comp.name, n_for, n_against)
    out.update(
        testable_predictions=h.testable_predictions, evidence_needed=h.evidence_needed, evidence=evidence,
        belief_history=[{"ts": b.ts, "confidence": b.confidence, "delta": b.delta, "reason": b.reason, "evidence_ids": b.evidence_ids}
                        for b in db.scalars(select(BeliefHistory).where(BeliefHistory.hypothesis_id == hid).order_by(BeliefHistory.ts, BeliefHistory.id))],
        challenges=[{"id": c.id, "alternative": c.alternative, "discriminating_test": c.discriminating_test,
                     "test_result": c.test_result, "verdict": c.verdict, "evidence_ids": c.evidence_ids, "created_at": c.created_at}
                    for c in db.scalars(select(SkepticChallenge).where(SkepticChallenge.hypothesis_id == hid))],
        investigations=[{"id": i.id, "started_at": i.started_at, "plan": i.plan, "actions": i.actions, "findings": i.findings,
                         "stop_reason": i.stop_reason, "tokens": i.tokens}
                        for i in db.scalars(select(Investigation).where(Investigation.hypothesis_id == hid).order_by(Investigation.id))],
        predictions=[{"id": p.id, "claim": p.claim, "made_at": p.made_at, "horizon_days": p.horizon_days, "resolve_by": p.resolve_by,
                      "confidence_at_creation": p.confidence_at_creation, "outcome": p.outcome, "resolved_at": p.resolved_at,
                      "evidence_id": p.evidence_id}
                     for p in db.scalars(select(Prediction).where(Prediction.hypothesis_id == hid))],
    )
    return out


# ---------- alerts ----------
@app.get("/alerts")
def list_alerts(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.execute(select(Alert, Competitor.name).join(Competitor, Competitor.id == Alert.competitor_id)
                      .order_by(Alert.created_at.desc()).limit(min(limit, 500))).all()
    return [{"id": a.id, "competitor": n, "hypothesis_id": a.hypothesis_id, "signal_id": a.signal_id, "priority": a.priority,
             "title": a.title, "body": a.body, "created_at": a.created_at, "feedback": a.feedback} for a, n in rows]


class FeedbackIn(BaseModel):
    useful: bool
    note: str | None = None


@app.post("/alerts/{aid}/feedback", status_code=201)
def alert_feedback(aid: int, body: FeedbackIn, db: Session = Depends(get_db)):
    a = db.get(Alert, aid)
    if not a:
        raise HTTPException(404, "alert not found")
    db.add(UserFeedback(alert_id=aid, useful=body.useful, note=body.note))
    a.feedback = "useful" if body.useful else "noise"
    db.commit()
    return {"ok": True}


@app.get("/agent-runs")
def agent_runs(kind: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    q = select(AgentRun)
    if kind:
        q = q.where(AgentRun.kind == kind)
    rows = db.scalars(q.order_by(AgentRun.id.desc()).limit(min(limit, 500))).all()
    return [{"id": r.id, "kind": r.kind, "started_at": r.started_at, "ended_at": r.ended_at, "model": r.model,
             "tokens_in": r.tokens_in, "tokens_out": r.tokens_out, "error": r.error, "output": r.output} for r in rows]
