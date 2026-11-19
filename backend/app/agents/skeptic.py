"""Skeptic: argue the mundane explanation, then actually RUN a discriminating test for each one.

Two LLM calls: (1) >= 2 concrete alternatives, each with a tool-executable test (validation rejects
mere disagreement); (2) a strict verdict per alternative given the real tool output.
Surviving alternatives lower confidence in the Judge; refuted ones slightly strengthen it.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import llm
from app.agents import prompts
from app.agents.investigator import _evidence_lines
from app.agents.schemas import SkepticOut, VerdictsOut
from app.agents.tools import ToolContext, run_tool, tool_menu
from app.db.models import Hypothesis, SkepticChallenge

log = logging.getLogger("veyra.skeptic")


def challenge(db: Session, hyp: Hypothesis, ctx: ToolContext, now: datetime) -> list[SkepticChallenge]:
    user = (f"Competitor: {ctx.competitor.name} ({ctx.competitor.domain})\nH{hyp.id} [{hyp.category}] {hyp.statement}\n"
            f"Confidence {hyp.confidence:.2f}\nEvidence:\n{_evidence_lines(db, hyp)}")
    alts = llm.complete_json(role="strong", system=prompts.SKEPTIC.format(tools=tool_menu()), user=user,
                             schema=SkepticOut, kind="skeptic")
    if alts is None:
        return []
    results = [run_tool(ctx, a.discriminating_test.tool, a.discriminating_test.args) for a in alts.alternatives]
    blocks = []
    for i, (a, r) in enumerate(zip(alts.alternatives, results)):
        t = a.discriminating_test
        blocks.append(f"[{i}] ALTERNATIVE: {a.alternative}\nTEST: {t.tool}({t.args})\n"
                      f"favours alternative if: {t.favors_alternative_if}\nfavours hypothesis if: {t.favors_hypothesis_if}\n"
                      f"ACTUAL OUTPUT:\n{r.text[:1200]}")
    verdicts = llm.complete_json(role="strong", system=prompts.SKEPTIC_VERDICT,
                                 user=f"Hypothesis: {hyp.statement}\n\n" + "\n\n".join(blocks),
                                 schema=VerdictsOut, kind="skeptic_verdict")
    by_idx = {v.index: v for v in (verdicts.verdicts if verdicts else [])}
    out = []
    for i, (a, r) in enumerate(zip(alts.alternatives, results)):
        v = by_idx.get(i)
        # citations must come from the tool output, otherwise they are dropped
        cited = [sid for sid in (v.cited_signal_ids if v else []) if sid in ctx.seen_signal_ids]
        urls = [u for u in (v.cited_urls if v else []) if u in ctx.seen_urls]
        verdict = v.verdict if v else "inconclusive"
        note = ""
        if verdict != "inconclusive" and not r.items:
            # Absence of evidence isn't evidence: an empty, failed or disabled test can't support OR refute anything.
            # (The model refuted alternatives on "no matching signals" despite the prompt saying so.)
            verdict, note = "inconclusive", f" [verdict '{v.verdict}' overridden: the test returned no data]"
        c = SkepticChallenge(
            hypothesis_id=hyp.id, alternative=a.alternative,
            discriminating_test=(f"{a.discriminating_test.tool}({a.discriminating_test.args}) | favours alternative if: "
                                 f"{a.discriminating_test.favors_alternative_if} | favours hypothesis if: "
                                 f"{a.discriminating_test.favors_hypothesis_if}"),
            test_result=(v.test_result if v else f"no verdict produced; raw output: {r.text[:300]}") + note
                        + (f"\nsources: {', '.join(urls)}" if urls else ""),
            verdict=verdict, evidence_ids=cited, created_at=now)
        db.add(c)
        out.append(c)
    ctx.calls.clear()
    db.flush()
    return out


def recently_challenged(db: Session, hyp: Hypothesis, now: datetime, days: int = 7) -> bool:
    last = db.scalars(select(SkepticChallenge.created_at).where(SkepticChallenge.hypothesis_id == hyp.id)
                      .order_by(SkepticChallenge.created_at.desc()).limit(1)).first()
    if last is None:
        return False
    last = last if last.tzinfo else last.replace(tzinfo=now.tzinfo)
    return (now - last).days < days
