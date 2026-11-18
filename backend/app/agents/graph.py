"""LangGraph agent graph, run once per competitor per cycle.

    strategist -> judge -> investigator -> judge -> skeptic -> judge -> alerts -> END

Only strategist / investigator / skeptic call an LLM. The judge, selection rules, alert policy and
prediction registry are deterministic Python. The DB session lives in the closure, not the state,
so the state stays small and JSON-serialisable for logging.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import llm
from app.agents import judge
from app.agents.investigator import investigate
from app.agents.skeptic import challenge, recently_challenged
from app.agents.strategist import OPEN, run_strategist
from app.agents.tools import CycleBudget, ToolContext
from app.config import get_settings
from app.db.models import Competitor, Hypothesis, SkepticChallenge
from app.db.session import log_agent_run

log = logging.getLogger("veyra.graph")


class AgentState(TypedDict, total=False):
    competitor_id: int
    as_of: str | None
    new_signal_ids: list[int]
    touched_ids: list[int]
    prev_status: dict[int, str]
    investigated: list[dict]
    challenged: list[dict]
    alerts: list[int]
    log: list[str]


def build_graph(db: Session, comp: Competitor, now: datetime, as_of: datetime | None, cycle_budget: CycleBudget):
    s = get_settings()
    ctx = ToolContext(db=db, competitor=comp, as_of=as_of, cycle_budget=cycle_budget)

    def open_hyps() -> list[Hypothesis]:
        return db.scalars(select(Hypothesis).where(Hypothesis.competitor_id == comp.id, Hypothesis.status.in_(OPEN))).all()

    def strategist_node(st: AgentState) -> AgentState:
        st["prev_status"] = {h.id: h.status for h in open_hyps()}
        r = run_strategist(db, comp, now, as_of)
        st["touched_ids"] = sorted(set(r["touched_ids"]) | set(r["new_hypothesis_ids"]))
        st["log"].append(f"strategist: reviewed {r['signals_reviewed']} signals, {r['links']} links, "
                         f"new hypotheses {r['new_hypothesis_ids']}, dropped {r.get('dropped_invalid_citations', 0)} bad citations"
                         + (f", error: {r['error']}" if r.get("error") else ""))
        return st

    def judge_node(label: str):
        def _judge(st: AgentState) -> AgentState:
            for hid in st.get("touched_ids", []):
                h = db.get(Hypothesis, hid)
                d = judge.rescore(db, h, now, f"judge after {label}")
                st["log"].append(f"judge[{label}]: H{hid} -> {h.confidence:.2f} ({d:+.2f}) {h.status}")
            return st
        return _judge

    def investigator_node(st: AgentState) -> AgentState:
        lo, hi = s.uncertain_band
        open_challenges = {c.hypothesis_id for c in db.scalars(select(SkepticChallenge).where(
            SkepticChallenge.verdict == "inconclusive"))}
        cands = [h for h in open_hyps() if lo <= h.confidence <= hi or h.id in open_challenges]
        # most uncertain first (closest to the middle of the band)
        cands.sort(key=lambda h: abs(h.confidence - (lo + hi) / 2))
        for h in cands[: s.max_investigations_per_cycle]:
            why = "confidence in uncertain band" if lo <= h.confidence <= hi else "open inconclusive skeptic challenge"
            inv = investigate(db, h, ctx, now, why)
            st["investigated"].append({"hypothesis_id": h.id, "investigation_id": inv.id, "stop_reason": inv.stop_reason,
                                       "findings": len([f for f in inv.findings if f.get("signal_id")])})
            st["touched_ids"] = sorted(set(st["touched_ids"]) | {h.id})
            st["log"].append(f"investigator: H{h.id} {inv.stop_reason}, conf {h.confidence:.2f}")
        return st

    def skeptic_node(st: AgentState) -> AgentState:
        cands = [h for h in open_hyps() if h.confidence >= s.skeptic_threshold and not recently_challenged(db, h, now)]
        cands.sort(key=lambda h: -h.confidence)
        for h in cands[: s.max_skeptic_per_cycle]:
            cs = challenge(db, h, ctx, now)
            st["challenged"].append({"hypothesis_id": h.id, "verdicts": [c.verdict for c in cs]})
            st["touched_ids"] = sorted(set(st["touched_ids"]) | {h.id})
            st["log"].append(f"skeptic: H{h.id} -> {[c.verdict for c in cs]}")
        return st

    def alerts_node(st: AgentState) -> AgentState:
        for hid in st.get("touched_ids", []):
            h = db.get(Hypothesis, hid)
            judge.register_predictions(db, h, now)
            a = judge.alert_policy(db, comp, h, st["prev_status"].get(hid, "emerging"), now)
            if a:
                st["alerts"].append(a.id)
        st["alerts"] += [a.id for a in judge.signal_alerts(db, comp, st.get("new_signal_ids", []), now)]
        n = judge.resolve_predictions(db, now)
        st["log"].append(f"alerts: {len(st['alerts'])} raised; {n} prediction(s) resolved")
        return st

    g = StateGraph(AgentState)
    g.add_node("strategist", strategist_node)
    g.add_node("judge_1", judge_node("strategist"))
    g.add_node("investigator", investigator_node)
    g.add_node("judge_2", judge_node("investigator"))
    g.add_node("skeptic", skeptic_node)
    g.add_node("judge_3", judge_node("skeptic"))
    g.add_node("alert_policy", alerts_node)
    g.set_entry_point("strategist")
    for a, b in [("strategist", "judge_1"), ("judge_1", "investigator"), ("investigator", "judge_2"),
                 ("judge_2", "skeptic"), ("skeptic", "judge_3"), ("judge_3", "alert_policy"), ("alert_policy", END)]:
        g.add_edge(a, b)
    return g.compile()


def run_agents_for(db: Session, comp: Competitor, *, new_signal_ids: list[int] | None = None,
                   as_of: datetime | None = None, cycle_budget: CycleBudget | None = None) -> dict[str, Any]:
    """Run the whole graph for one competitor inside the caller's transaction."""
    s = get_settings()
    now = as_of or datetime.now(timezone.utc)
    started = datetime.now(timezone.utc)
    comp_name = comp.name  # read before anything can expire the instance
    budget = llm.start_budget(s.run_max_tokens)
    graph = build_graph(db, comp, now, as_of, cycle_budget or CycleBudget(s.cycle_max_fetches))
    state: AgentState = {"competitor_id": comp.id, "as_of": as_of.isoformat() if as_of else None,
                         "new_signal_ids": new_signal_ids or [], "touched_ids": [], "prev_status": {},
                         "investigated": [], "challenged": [], "alerts": [], "log": []}
    error = None
    try:
        state = graph.invoke(state)
    except Exception as e:  # noqa: BLE001 - logged to agent_runs, cycle continues
        log.exception("agent graph failed for %s", comp_name)
        error = f"{type(e).__name__}: {str(e)[:500]}"
        state["log"].append(f"ERROR {error}")
        db.rollback()  # discard this competitor's partial agent writes; the audit row below still lands
    out = {k: state.get(k) for k in ("touched_ids", "investigated", "challenged", "alerts", "log")}
    out["tokens_used"], out["llm_calls"] = budget.used, budget.calls
    log_agent_run("agent_graph", started, {"competitor": comp_name, "as_of": state.get("as_of")}, out,
                  tokens_in=budget.used, error=error)
    return out
