"""Copy a replay run's hypotheses (and everything they depend on) into the live DB, badged Replay.

    python -m app.eval.import_replay ../data/eval/replay_masked_<stamp>.db

The dashboard reads the live database; this lets a backtest's hypotheses (with their full belief timelines,
evidence for/against, skeptic tests and investigations) be browsed on the Hypotheses page. Every copied
hypothesis and signal has replay=True, so live views, chat and briefs keep excluding them, and the UI badges them.
Re-importing the same file first removes that file's previous import (tracked in hypothesis notes).
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import (BeliefHistory, Competitor, Hypothesis, HypothesisEvidence, Investigation, Prediction,
                           Signal, SkepticChallenge)
from app.db.session import SessionLocal, init_db

COPY_SIGNAL = ("type", "category", "summary", "old_value", "new_value", "evidence_url", "observed_at", "detected_at",
               "origin_group", "event_confidence", "priority", "raw", "synthetic")


def _tag(path: Path) -> str:
    return f"replay-import:{path.name}"


def import_run(path: Path) -> dict:
    init_db()
    src = Session(create_engine(f"sqlite:///{path.resolve().as_posix()}"))
    with SessionLocal() as live:
        tag = _tag(path)
        old = live.scalars(select(Hypothesis).where(Hypothesis.evidence_needed.is_not(None))).all()
        for h in [h for h in old if tag in (h.evidence_needed or [])]:
            live.delete(h)
        live.query(Signal).filter(Signal.dedup_key.like(f"{path.name[:40]}:%")).delete(synchronize_session=False)
        live.flush()

        live_comp = {c.name: c.id for c in live.scalars(select(Competitor))}
        src_comp = {c.id: c.name for c in src.scalars(select(Competitor))}
        sig_map: dict[int, int] = {}
        n_h = 0
        for h in src.scalars(select(Hypothesis).where(Hypothesis.synthetic.is_(False))):
            cid = live_comp.get(src_comp.get(h.competitor_id, ""))
            if cid is None:
                continue
            nh = Hypothesis(competitor_id=cid, statement=h.statement, category=h.category, status=h.status,
                            confidence=h.confidence, prior=h.prior, created_at=h.created_at, updated_at=h.updated_at,
                            closed_at=h.closed_at, testable_predictions=h.testable_predictions,
                            evidence_needed=[*(h.evidence_needed or []), tag], replay=True)
            live.add(nh)
            live.flush()
            n_h += 1
            for he in src.scalars(select(HypothesisEvidence).where(HypothesisEvidence.hypothesis_id == h.id)):
                if he.signal_id not in sig_map:
                    s = src.get(Signal, he.signal_id)
                    ns = Signal(competitor_id=cid, source_id=None, replay=True,
                                dedup_key=f"{path.name[:40]}:{s.id}", **{k: getattr(s, k) for k in COPY_SIGNAL})
                    live.add(ns)
                    live.flush()
                    sig_map[s.id] = ns.id
                live.add(HypothesisEvidence(hypothesis_id=nh.id, signal_id=sig_map[he.signal_id], stance=he.stance,
                                            relevance=he.relevance, reliability=he.reliability,
                                            independence_weight=he.independence_weight, contribution=he.contribution,
                                            rationale=he.rationale, added_by=he.added_by, created_at=he.created_at))
            for b in src.scalars(select(BeliefHistory).where(BeliefHistory.hypothesis_id == h.id)):
                live.add(BeliefHistory(hypothesis_id=nh.id, ts=b.ts, confidence=b.confidence, delta=b.delta, reason=b.reason,
                                       evidence_ids=[sig_map.get(i, i) for i in (b.evidence_ids or [])]))
            for c in src.scalars(select(SkepticChallenge).where(SkepticChallenge.hypothesis_id == h.id)):
                live.add(SkepticChallenge(hypothesis_id=nh.id, alternative=c.alternative, discriminating_test=c.discriminating_test,
                                          test_result=c.test_result, verdict=c.verdict, created_at=c.created_at,
                                          evidence_ids=[sig_map.get(i, i) for i in (c.evidence_ids or [])]))
            for i in src.scalars(select(Investigation).where(Investigation.hypothesis_id == h.id)):
                live.add(Investigation(hypothesis_id=nh.id, started_at=i.started_at, plan=i.plan, actions=i.actions,
                                       findings=[{**f, "signal_id": sig_map.get(f.get("signal_id"), f.get("signal_id"))}
                                                 for f in (i.findings or [])],
                                       stop_reason=i.stop_reason, tokens=i.tokens))
            for p in src.scalars(select(Prediction).where(Prediction.hypothesis_id == h.id)):
                live.add(Prediction(hypothesis_id=nh.id, claim=p.claim, made_at=p.made_at, horizon_days=p.horizon_days,
                                    resolve_by=p.resolve_by, confidence_at_creation=p.confidence_at_creation,
                                    outcome=p.outcome, resolved_at=p.resolved_at, evidence_id=sig_map.get(p.evidence_id)))
        live.commit()
    src.close()
    return {"hypotheses": n_h, "signals": len(sig_map), "source": path.name}


if __name__ == "__main__":
    if len(sys.argv) != 2 or not Path(sys.argv[1]).exists():
        sys.exit("usage: python -m app.eval.import_replay <replay.db>")
    print(import_run(Path(sys.argv[1])))
