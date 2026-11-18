"""Investigator: autonomous, BOUNDED follow-up research on one uncertain hypothesis.

Loop: LLM step (plan / record findings / choose tool) -> run tool -> rescore -> ...
Stop conditions (whichever first):
  * the model says stop (question answered / nothing more to learn)
  * hard budget: investigator_max_tool_calls per hypothesis, cycle fetch budget, run token budget
  * convergence: after >= 2 tool calls, the last two steps moved confidence by < investigator_min_delta
Findings may cite ONLY signal ids / urls that a tool actually returned (else dropped).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import llm
from app.agents import prompts
from app.agents.judge import link_evidence, rescore
from app.agents.schemas import InvestigatorStep
from app.agents.tools import ToolContext, run_tool, tool_menu
from app.collectors.base import sha
from app.config import get_settings
from app.db.models import HypothesisEvidence, Hypothesis, Investigation, Signal
from app.db.session import log_agent_run

log = logging.getLogger("veyra.investigator")


def _evidence_lines(db: Session, hyp: Hypothesis) -> str:
    rows = db.execute(select(HypothesisEvidence, Signal).join(Signal, Signal.id == HypothesisEvidence.signal_id)
                      .where(HypothesisEvidence.hypothesis_id == hyp.id)).all()
    return "\n".join(f"- {he.stance} S{s.id} ({s.type}, {s.observed_at:%Y-%m-%d}): {s.summary[:160]}" for he, s in rows) or "(none)"


def known_signal_for_url(db: Session, competitor_id: int, url: str) -> tuple[Signal | None, str | None]:
    """(signal whose evidence IS this url, or None; origin_group of a signal that already CONTAINS this url).
    Stops re-discovered facts (e.g. postings already summarised by a hiring signal) counting as new evidence."""
    exact = db.scalars(select(Signal).where(Signal.competitor_id == competitor_id, Signal.evidence_url == url)
                       .order_by(Signal.id).limit(1)).first()
    if exact:
        return exact, exact.origin_group
    for s in db.scalars(select(Signal).where(Signal.competitor_id == competitor_id, Signal.type != "investigation_finding")):
        if url in json.dumps(s.raw or {}):
            return None, s.origin_group
    return None, None


def _finding_signal(db: Session, ctx: ToolContext, hyp: Hypothesis, url: str, summary: str, now: datetime) -> Signal:
    """A URL-backed finding becomes an `investigation_finding` signal so it can carry evidence weight -
    unless the URL is already an existing signal's evidence (reuse it) or part of one (share its origin group)."""
    exact, group = known_signal_for_url(db, hyp.competitor_id, url)
    if exact:
        return exact
    key = sha(f"{hyp.competitor_id}|investigation_finding|{hyp.id}|{url}")[:64]
    existing = db.scalar(select(Signal).where(Signal.dedup_key == key))
    if existing:
        return existing
    snippet = next((c["result"] for c in reversed(ctx.calls) if url in c["result"]), "")
    s = Signal(competitor_id=hyp.competitor_id, source_id=None, type="investigation_finding", category=hyp.category,
               summary=summary[:400], new_value=snippet[:300] or None, evidence_url=url, observed_at=now,
               detected_at=now, origin_group=group or f"inv:{hyp.id}:{sha(url)[:10]}", event_confidence=0.9, priority="low",
               dedup_key=key, raw={"added_by": "investigator", "classified_by": "llm", "joined_existing_group": bool(group)},
               replay=ctx.replay)
    db.add(s)
    db.flush()
    return s


def investigate(db: Session, hyp: Hypothesis, ctx: ToolContext, now: datetime, reason: str) -> Investigation:
    s = get_settings()
    inv = Investigation(hypothesis_id=hyp.id, started_at=now, plan=[], actions=[], findings=[])
    db.add(inv)
    db.flush()
    budget = llm.current_budget()
    tokens_before = budget.used if budget else 0
    system = prompts.INVESTIGATOR.format(competitor=ctx.competitor.name, tools=tool_menu())
    header = (f"H{hyp.id} [{hyp.category}] {hyp.statement}\nCurrent confidence {hyp.confidence:.2f} ({hyp.status}). "
              f"Why investigate: {reason}\nEvidence needed: {'; '.join(hyp.evidence_needed or []) or 'n/a'}\n"
              f"Known evidence:\n{_evidence_lines(db, hyp)}\nBudget: at most {s.investigator_max_tool_calls} tool calls.")
    transcript: list[str] = []
    deltas: list[float] = []
    stop_reason = None
    tool_calls = 0
    start_conf = hyp.confidence
    pending_result = False

    while True:
        forced_stop = tool_calls >= s.investigator_max_tool_calls
        user = header + "\n\n" + "\n".join(transcript[-8:])
        if forced_stop:
            user += "\n\nBUDGET EXHAUSTED: record findings from the last result and set action to stop."
        step = llm.complete_json(role=s.investigator_role, system=system, user=user, schema=InvestigatorStep,
                                 kind="investigator_step")  # type: ignore[arg-type]
        if step is None:
            stop_reason = "llm_failed_or_token_budget"
            break
        if step.plan and not inv.plan:
            inv.plan = step.plan
        # --- record findings (validated against what tools actually returned) ---
        added = []
        for f in step.findings:
            sig = None
            if f.signal_id is not None and f.signal_id in ctx.seen_signal_ids:
                sig = db.get(Signal, f.signal_id)
            elif f.url and f.url in ctx.seen_urls:
                sig = _finding_signal(db, ctx, hyp, f.url, f.summary, now)
            if sig is None:
                inv.findings = [*inv.findings, {"dropped": True, "summary": f.summary, "why": "cited nothing a tool returned"}]
                continue
            if link_evidence(db, hyp, sig, f.stance, f.relevance, f.summary, "investigator", ctx.competitor.domain):
                added.append(sig.id)
            inv.findings = [*inv.findings, {"signal_id": sig.id, "url": sig.evidence_url, "summary": f.summary,
                                            "stance": f.stance, "relevance": f.relevance}]
        if pending_result:
            d = rescore(db, hyp, now, "investigator step", write_history=False)
            deltas.append(abs(d) if added else 0.0)
            transcript.append(f"OBSERVATION: {step.observation} (confidence now {hyp.confidence:.2f})")
        if step.action == "stop" or forced_stop:
            stop_reason = "budget_exhausted" if forced_stop else f"agent_stopped: {step.stop_reason or 'answered'}"
            break
        if tool_calls >= 2 and len(deltas) >= 2 and max(deltas[-2:]) < s.investigator_min_delta:
            stop_reason = f"converged: last two steps moved confidence < {s.investigator_min_delta}"
            break
        if budget and budget.exhausted:
            stop_reason = "token_budget_exhausted"
            break
        res = run_tool(ctx, step.action, step.args)
        tool_calls += 1
        pending_result = True
        inv.actions = [*inv.actions, {"tool": step.action, "args": step.args, "result": res.text[:800]}]
        transcript.append(f"CALL {tool_calls}: {step.action}({step.args})\nRESULT:\n{res.text[:1400]}")

    inv.stop_reason = stop_reason
    inv.tokens = (budget.used - tokens_before) if budget else 0
    ev_ids = [f["signal_id"] for f in inv.findings if f.get("signal_id")]
    rescore(db, hyp, now, f"investigation #{inv.id}: {len(ev_ids)} finding(s), {tool_calls} tool call(s); {stop_reason}",
            evidence_ids=ev_ids)
    log_agent_run("investigation", now, {"hypothesis_id": hyp.id, "start_confidence": start_conf},
                  {"end_confidence": hyp.confidence, "stop_reason": stop_reason, "findings": inv.findings},
                  tool_calls=list(ctx.calls), tokens_in=inv.tokens)
    ctx.calls.clear()
    db.flush()
    return inv
