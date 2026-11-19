"""Strategist (LLM_STRONG): link new signals to hypotheses (stance/relevance) and propose <= 2 new ones."""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import llm
from app.agents import prompts
from app.agents.judge import link_evidence
from app.agents.schemas import SIGNAL_TYPES, StrategistOut
from app.belief import engine as be
from app.config import get_settings
from app.db.models import AgentCursor, BeliefHistory, Competitor, Hypothesis, HypothesisEvidence, Signal

log = logging.getLogger("veyra.strategist")
PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
OPEN = ("emerging", "plausible", "likely", "confirmed")


def _strength(sig: Signal) -> str:
    if sig.category == "early_signal":
        return "early-signal lead (weak)"
    kind = (sig.raw or {}).get("kind")
    return "official" if kind == "blog" or sig.type.startswith(("price", "plan", "hiring")) or kind is None else "news"


def pick_signals(db: Session, comp: Competitor, as_of: datetime | None) -> tuple[list[Signal], int]:
    cur = db.get(AgentCursor, comp.id)
    last = cur.last_signal_id if cur else 0
    q = select(Signal).where(Signal.competitor_id == comp.id, Signal.id > last)
    if as_of:
        q = q.where(Signal.observed_at <= as_of)
    unseen = db.scalars(q).all()
    max_id = max((s.id for s in unseen), default=last)
    unseen.sort(key=lambda s: (PRIORITY_RANK.get(s.priority, 4), -s.observed_at.timestamp()))
    return unseen[: get_settings().strategist_max_signals], max_id


def run_strategist(db: Session, comp: Competitor, now: datetime, as_of: datetime | None = None) -> dict:
    signals, max_id = pick_signals(db, comp, as_of)
    out = {"signals_reviewed": len(signals), "links": 0, "new_hypothesis_ids": [], "touched_ids": []}
    if not signals:
        return out
    open_hyps = db.scalars(select(Hypothesis).where(Hypothesis.competitor_id == comp.id, Hypothesis.status.in_(OPEN))).all()
    closed = db.scalars(select(Hypothesis).where(Hypothesis.competitor_id == comp.id, Hypothesis.status.not_in(OPEN))
                        .order_by(Hypothesis.updated_at.desc()).limit(5)).all()
    counts = dict(db.execute(select(HypothesisEvidence.hypothesis_id, func.count()).group_by(HypothesisEvidence.hypothesis_id)).all())

    sig_lines = "\n".join(
        f"S{s.id} [{s.category}/{s.type}/{s.priority}, {s.observed_at:%Y-%m-%d}, {_strength(s)}, group={s.origin_group[:24]}] "
        f"{s.summary[:220]}" for s in signals)
    hyp_lines = "\n".join(f"H{h.id} ({h.status}, {h.confidence:.2f}, {counts.get(h.id, 0)} evidence) [{h.category}] {h.statement}"
                          for h in open_hyps) or "(none yet)"
    memory = "\n".join(f"- closed ({h.status}): {h.statement}" for h in closed) or "(none)"
    cursor = db.get(AgentCursor, comp.id)
    last_note = f"- last cycle's note: {cursor.memory_note}" if cursor and cursor.memory_note else ""
    user = (f"Competitor: {comp.name} ({comp.domain})\nAllowed signal_types for predictions: {', '.join(SIGNAL_TYPES)}\n\n"
            f"NEW SIGNALS:\n{sig_lines}\n\nOPEN HYPOTHESES:\n{hyp_lines}\n\nMEMORY:\n{memory}\n{last_note or ''}")
    res = llm.complete_json(role="strong", system=prompts.STRATEGIST.format(competitor=comp.name), user=user,
                            schema=StrategistOut, kind="strategist")
    if res is None:  # don't advance the cursor: these signals get reviewed next cycle instead of being lost
        out["error"] = "strategist output invalid or LLM unavailable"
        return out
    _advance_cursor(db, comp, max_id, now, res.memory_note)

    shown = {s.id: s for s in signals}
    by_hyp = {h.id: h for h in open_hyps}
    dropped = 0
    out["merged_groups"] = merge_same_event(db, shown, res.same_event_groups)
    for ln in res.links:  # never accept evidence the strategist was not shown
        if ln.signal_id not in shown or ln.hypothesis_id not in by_hyp:
            dropped += 1
            continue
        if link_evidence(db, by_hyp[ln.hypothesis_id], shown[ln.signal_id], ln.stance, ln.relevance, ln.rationale,
                         "strategist", comp.domain):
            out["links"] += 1
            if ln.hypothesis_id not in out["touched_ids"]:
                out["touched_ids"].append(ln.hypothesis_id)
    for nh in res.new_hypotheses[: get_settings().strategist_max_new_hypotheses]:
        valid = [ln for ln in nh.links if ln.signal_id in shown]
        dropped += len(nh.links) - len(valid)
        if not valid:
            continue
        prior = be.PRIOR.get(nh.category, 0.2)
        h = Hypothesis(competitor_id=comp.id, statement=nh.statement, category=nh.category, status="emerging",
                       confidence=prior, prior=prior, created_at=now, updated_at=now,
                       testable_predictions=[p.model_dump() for p in nh.testable_predictions],
                       evidence_needed=nh.evidence_needed, replay=as_of is not None)
        db.add(h)
        db.flush()
        db.add(BeliefHistory(hypothesis_id=h.id, ts=now, confidence=prior, delta=0.0,
                             reason=f"created by strategist with category prior {prior:.2f}", evidence_ids=[]))
        for ln in valid:
            if link_evidence(db, h, shown[ln.signal_id], ln.stance, ln.relevance, ln.rationale, "strategist", comp.domain):
                out["links"] += 1
        out["new_hypothesis_ids"].append(h.id)
    out["dropped_invalid_citations"] = dropped
    out["memory_note"] = res.memory_note
    db.flush()
    return out


def _advance_cursor(db: Session, comp: Competitor, max_id: int, now: datetime, note: str | None) -> None:
    cur = db.get(AgentCursor, comp.id)
    if cur is None:
        db.add(AgentCursor(competitor_id=comp.id, last_signal_id=max_id, updated_at=now, memory_note=note))
    else:
        cur.last_signal_id, cur.updated_at = max(cur.last_signal_id, max_id), now
        cur.memory_note = note or cur.memory_note
    db.flush()


MERGEABLE_KINDS = ("news", "blog")  # only reports ABOUT events can be duplicates of each other


def merge_same_event(db: Session, shown: dict[int, Signal], groups: list[list[int]]) -> int:
    """Give news/blog items the strategist says report one event a shared origin_group (independence weighting).
    Deterministic Jaccard grouping runs at ingest; this catches paraphrased headlines it misses.
    Direct observations (page diffs, job boards, CT logs, sitemaps) are never merged: each is its own
    evidence, and letting the LLM merge them would let it erase independence (caught by the synthetic test)."""
    merged = 0
    for g in groups:
        sigs = [shown[i] for i in dict.fromkeys(g) if i in shown and (shown[i].raw or {}).get("kind") in MERGEABLE_KINDS]
        if len(sigs) < 2:
            continue
        sigs.sort(key=lambda s: s.observed_at)
        root = sigs[0].origin_group
        for s in sigs[1:]:
            if s.origin_group != root:
                s.raw = {**(s.raw or {}), "origin_group_before_merge": s.origin_group, "merged_by": "strategist"}
                s.origin_group = root
                merged += 1
    db.flush()
    return merged
