"""Judge: deterministic belief update + status + alert policy + predictions registry. NOT an LLM."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.belief import engine as be
from app.config import get_settings
from app.db.models import (Alert, BeliefHistory, Competitor, Hypothesis, HypothesisEvidence, Prediction, Signal,
                           SkepticChallenge, Source)

log = logging.getLogger("veyra.judge")


def link_evidence(db: Session, hyp: Hypothesis, sig: Signal, stance: str, relevance: float, rationale: str,
                  added_by: str, competitor_domain: str = "") -> HypothesisEvidence | None:
    """Attach a signal to a hypothesis once (re-linking the same signal updates nothing)."""
    if db.scalar(select(HypothesisEvidence.id).where(HypothesisEvidence.hypothesis_id == hyp.id,
                                                     HypothesisEvidence.signal_id == sig.id)):
        return None
    src_type = db.scalar(select(Source.source_type).where(Source.id == sig.source_id)) if sig.source_id else None
    he = HypothesisEvidence(
        hypothesis_id=hyp.id, signal_id=sig.id, stance=stance, relevance=float(relevance),
        reliability=be.source_reliability(src_type, sig.raw or {}, sig.evidence_url, competitor_domain),
        rationale=rationale[:500], added_by=added_by)
    db.add(he)
    db.flush()
    return he


def _items(db: Session, hyp: Hypothesis) -> tuple[list[be.EvidenceItem], list[HypothesisEvidence]]:
    rows = db.execute(select(HypothesisEvidence, Signal).join(Signal, Signal.id == HypothesisEvidence.signal_id)
                      .where(HypothesisEvidence.hypothesis_id == hyp.id)).all()
    items, hes = [], []
    for he, sig in rows:
        items.append(be.EvidenceItem(id=he.id, stance=he.stance, relevance=he.relevance, reliability=he.reliability,
                                     event_confidence=sig.event_confidence, observed_at=sig.observed_at,
                                     origin_group=sig.origin_group, category=sig.category))
        hes.append(he)
    return items, hes


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def rescore(db: Session, hyp: Hypothesis, now: datetime, reason: str, *, write_history: bool = True,
            evidence_ids: list[int] | None = None) -> float:
    """Recompute confidence + status from all evidence and skeptic verdicts. Returns the delta."""
    items, hes = _items(db, hyp)
    # SQLite returns naive datetimes; normalise so decay maths is right
    items = [be.EvidenceItem(**{**i.__dict__, "observed_at": _aware(i.observed_at)}) for i in items]
    verdicts = list(db.scalars(select(SkepticChallenge.verdict).where(SkepticChallenge.hypothesis_id == hyp.id)))
    res = be.score(hyp.prior, items, now, verdicts)
    for he in hes:
        he.contribution = round(res.contributions.get(he.id, 0.0), 4)
        he.independence_weight = res.independence.get(he.id, 1.0)
    prev = hyp.confidence
    max_seen = max([prev, *db.scalars(select(BeliefHistory.confidence).where(BeliefHistory.hypothesis_id == hyp.id))])
    by_id = {i.id: i for i in items}
    has_primary = any(he.stance == "supports" and he.reliability >= 1.0 and by_id[he.id].event_confidence >= 0.9 for he in hes)
    has_contra = any(he.stance == "contradicts" for he in hes)
    hyp.confidence = round(res.confidence, 4)
    hyp.status = be.status_for(hyp.confidence, max_confidence_seen=max_seen, has_primary_support=has_primary,
                               has_contradiction=has_contra)
    if hyp.status in ("likely", "confirmed") and not verdicts:
        hyp.status = "plausible"  # gate: nothing is raised to likely/confirmed before the skeptic has challenged it
    hyp.updated_at = now
    if hyp.status in ("refuted", "stale") and hyp.closed_at is None:
        hyp.closed_at = now
    delta = hyp.confidence - prev
    if write_history and (abs(delta) > 1e-4 or evidence_ids):
        db.add(BeliefHistory(hypothesis_id=hyp.id, ts=now, confidence=hyp.confidence, delta=round(delta, 4),
                             reason=reason[:500], evidence_ids=evidence_ids or []))
    db.flush()
    return delta


# ---------------- predictions ----------------
def register_predictions(db: Session, hyp: Hypothesis, now: datetime) -> list[Prediction]:
    if hyp.confidence < get_settings().prediction_threshold:
        return []
    if db.scalar(select(Prediction.id).where(Prediction.hypothesis_id == hyp.id)):
        return []
    out = []
    for tp in hyp.testable_predictions or []:
        p = Prediction(hypothesis_id=hyp.id, claim=tp["claim"], made_at=now, horizon_days=int(tp["horizon_days"]),
                       resolve_by=now + timedelta(days=int(tp["horizon_days"])), confidence_at_creation=hyp.confidence)
        db.add(p)
        out.append(p)
    db.flush()
    return out


def resolve_predictions(db: Session, now: datetime) -> int:
    """hit: a matching signal was observed after the prediction was made and before resolve_by.
    miss: horizon passed with no match. expired: hypothesis closed (refuted/stale) first."""
    n = 0
    for p in db.scalars(select(Prediction).where(Prediction.outcome == "open")).all():
        hyp = db.get(Hypothesis, p.hypothesis_id)
        spec = next((t for t in hyp.testable_predictions or [] if t.get("claim") == p.claim), None)
        if spec:
            rx = re.compile("|".join(re.escape(k) for k in spec.get("keywords", []) if k), re.I)
            q = select(Signal).where(Signal.competitor_id == hyp.competitor_id, Signal.type.in_(spec.get("signal_types", [])),
                                     Signal.observed_at > p.made_at, Signal.observed_at <= min(now, _aware(p.resolve_by)))
            hit = next((s for s in db.scalars(q).all() if rx.pattern and rx.search(f"{s.summary} {s.new_value or ''}")), None)
            if hit:
                p.outcome, p.resolved_at, p.evidence_id = "hit", now, hit.id
                n += 1
                continue
        if hyp.status in ("refuted", "stale"):
            p.outcome, p.resolved_at = "expired", now
            n += 1
        elif now > _aware(p.resolve_by):
            p.outcome, p.resolved_at = "miss", now
            n += 1
    db.flush()
    return n


# ---------------- alert policy ----------------
RAISED = ("likely", "confirmed")


def alert_policy(db: Session, comp: Competitor, hyp: Hypothesis, prev_status: str, now: datetime) -> Alert | None:
    """Alert when a hypothesis is raised to likely/confirmed AFTER the skeptic has challenged it."""
    if hyp.status not in RAISED or prev_status in RAISED:
        return None
    challenges = db.scalars(select(SkepticChallenge).where(SkepticChallenge.hypothesis_id == hyp.id)).all()
    if not challenges:
        return None  # never alert on an unchallenged claim
    surviving = [c for c in challenges if c.verdict == "alternative_supported"]
    strongest = (surviving or [c for c in challenges if c.verdict == "inconclusive"] or challenges)[0]
    body = (f"{be.band_label(hyp.confidence)} {hyp.confidence:.2f} (uncalibrated heuristic score)\n"
            f"Hypothesis: {hyp.statement}\n"
            f"Strongest alternative ({strongest.verdict.replace('_', ' ')}): {strongest.alternative}")
    a = Alert(competitor_id=comp.id, hypothesis_id=hyp.id, priority="high" if hyp.status == "likely" else "critical",
              title=f"{comp.name}: {hyp.statement[:200]}", body=body, created_at=now, channel="dashboard")
    db.add(a)
    db.flush()
    return a


def signal_alerts(db: Session, comp: Competitor, signal_ids: list[int], now: datetime) -> list[Alert]:
    """Critical signals (e.g. >20% price change) alert immediately, hypothesis or not."""
    out = []
    for s in db.scalars(select(Signal).where(Signal.id.in_(signal_ids), Signal.priority == "critical")).all():
        if db.scalar(select(Alert.id).where(Alert.signal_id == s.id)):
            continue
        a = Alert(competitor_id=comp.id, signal_id=s.id, priority="critical", title=f"{comp.name}: {s.summary[:200]}",
                  body=f"{s.summary}\nEvidence: {s.evidence_url}", created_at=now, channel="dashboard")
        db.add(a)
        out.append(a)
    db.flush()
    return out
