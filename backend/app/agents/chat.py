"""Ask Veyra: chat grounded in the database through read-only tools, with citations.

Same discipline as the investigator: the model picks tools by name in JSON (no native function
calling), at most MAX_TOOL_CALLS per question, and the final answer may cite ONLY signal / hypothesis
ids that a tool returned. Belief timelines in the response are built from `belief_history` by code,
so the model can describe a trajectory but can't invent its numbers.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import llm
from app.belief.engine import band_label
from app.db.models import BeliefHistory, Competitor, Hypothesis, HypothesisEvidence, SkepticChallenge, Signal

log = logging.getLogger("veyra.chat")
MAX_TOOL_CALLS = 4

CHAT_SYSTEM = (
    "You are Veyra, a competitive-intelligence analyst. Answer the user's question using ONLY data returned by "
    "your tools. Each step, either call one tool (put its name in `action` and arguments in `args`) or answer "
    "(`action`: \"answer\"). You have NO function-calling ability: tool use happens through this JSON only.\n"
    "Tools:\n{tools}\n"
    "Rules: for 'how has X evolved / changed over time' questions, call list_hypotheses then get_belief_history "
    "and describe the BELIEF TIMELINE (how confidence rose or fell and which evidence moved it), not a news "
    "summary. Cite every claim with ids that tools returned (signal ids like 12, hypothesis ids like 3) in "
    "`cited_signal_ids` / `cited_hypothesis_ids`. Say clearly when the data does not answer the question. "
    "Describe confidence ONLY with the status word the tools give (emerging, plausible, likely, confirmed) and say it is an uncalibrated score: never call a plausible or emerging hypothesis 'high confidence', never present scores as probabilities. Early signals (subdomains, sitemap paths) are leads, not proof. Keep answers under "
    "220 words, in Markdown."
)

TOOL_DOCS = {
    "list_hypotheses": 'hypotheses with status/confidence. args: {"competitor"?: name, "status"?: str, "keywords"?: [..]}',
    "get_belief_history": 'confidence over time + evidence + skeptic verdicts. args: {"hypothesis_id": int}',
    "query_signals": 'collected signals. args: {"competitor"?: name, "keywords"?: [..], "category"?: str, "days"?: int}',
    "compare_pricing": 'pricing/plan signals per competitor. args: {"competitors"?: [names], "days"?: int}',
    "search_evidence": 'full-text search over signal summaries and evidence rationales. args: {"keywords": [..]}',
}


class ChatStep(BaseModel):
    action: Literal["list_hypotheses", "get_belief_history", "query_signals", "compare_pricing", "search_evidence",
                    "answer"] = "answer"
    args: dict[str, Any] = Field(default_factory=dict)
    answer: str = Field(default="", max_length=4000)
    cited_signal_ids: list[int] = Field(default_factory=list, max_length=20)
    cited_hypothesis_ids: list[int] = Field(default_factory=list, max_length=10)

    @field_validator("cited_signal_ids", "cited_hypothesis_ids", mode="before")
    @classmethod
    def ints(cls, v):  # models sometimes write "S12" / "H3"
        if not isinstance(v, list):
            return v
        out = []
        for x in v:
            m = re.search(r"\d+", str(x))
            if m:
                out.append(int(m.group()))
        return out


@dataclass
class ChatContext:
    db: Session
    seen_signals: set[int] = field(default_factory=set)
    seen_hypotheses: set[int] = field(default_factory=set)
    calls: list[dict] = field(default_factory=list)


# ---------------- tools (read-only) ----------------
def _comp_ids(db: Session, names: list[str] | str | None) -> list[int] | None:
    if not names:
        return None
    names = [names] if isinstance(names, str) else names
    rows = db.scalars(select(Competitor).where(or_(*[Competitor.name.ilike(f"%{n}%") for n in names]))).all()
    return [c.id for c in rows]


STOPWORDS = {"the", "and", "for", "with", "how", "has", "have", "what", "which", "its", "their", "over", "time", "into",
             "evolution", "evolved", "evolve", "strategy", "strategic", "change", "changes", "changed", "recent", "latest",
             "about", "doing", "are", "was", "were", "does", "did", "this", "that", "from", "any", "all", "new"}


def _kws(v, drop: set[str] | None = None) -> list[str]:
    """Phrases -> distinct content words (models search with phrases that match nothing verbatim)."""
    if not v:
        return []
    items = [v] if isinstance(v, str) else [k for k in v if isinstance(k, str)]
    words: list[str] = []
    for item in items:
        for w in re.findall(r"[a-z0-9][a-z0-9\-\.]+", item.lower()):
            w = w.strip(".-")
            if len(w) >= 3 and w not in STOPWORDS and w not in (drop or set()) and w not in words:
                words.append(w)
    return words[:8]


def _competitor_names(db: Session) -> dict[str, int]:
    return {c.name.lower(): c.id for c in db.scalars(select(Competitor)) if not (c.notes or "").startswith("SYNTHETIC")}


def _split_competitors(db: Session, competitor, keywords) -> tuple[list[int] | None, list[str]]:
    """Company names inside keywords become a competitor filter, not search words."""
    names = _competitor_names(db)
    ids = _comp_ids(db, competitor)
    raw = " ".join([keywords] if isinstance(keywords, str) else [k for k in (keywords or []) if isinstance(k, str)]).lower()
    named = [cid for n, cid in names.items() if re.search(r"\b" + re.escape(n) + r"\b", raw)]
    if named:
        ids = sorted(set(ids or []) | set(named))
    return ids, _kws(keywords, drop=set(names))


def _rank(rows, text_of, words: list[str]):
    if not words:
        return rows
    scored = [(sum(w in text_of(r).lower() for w in words), i, r) for i, r in enumerate(rows)]
    return [r for sc, _, r in sorted(scored, key=lambda x: (-x[0], x[1])) if sc > 0]


def t_list_hypotheses(ctx: ChatContext, competitor=None, status=None, keywords=None, **_) -> str:
    q = select(Hypothesis, Competitor.name).join(Competitor, Competitor.id == Hypothesis.competitor_id).where(
        Hypothesis.synthetic.is_(False), Hypothesis.replay.is_(False))
    ids, kws = _split_competitors(ctx.db, competitor, keywords)
    if ids is not None:
        q = q.where(Hypothesis.competitor_id.in_(ids))
    if status:
        q = q.where(Hypothesis.status == status)
    rows = ctx.db.execute(q.order_by(Hypothesis.confidence.desc()).limit(30)).all()
    rows = (_rank(rows, lambda r: r[0].statement, kws) or rows)[:10]  # no keyword hit -> show the competitor's list
    ctx.seen_hypotheses |= {h.id for h, _ in rows}
    return "\n".join(f"H{h.id} [{n}, {h.category}] {h.status} {h.confidence:.2f} (since {h.created_at:%Y-%m-%d}): {h.statement}"
                     for h, n in rows) or "no matching hypotheses"


def t_get_belief_history(ctx: ChatContext, hypothesis_id=0, **_) -> str:
    try:
        hid = int(re.search(r"\d+", str(hypothesis_id)).group())
    except (AttributeError, ValueError):
        return "give a numeric hypothesis_id"
    h = ctx.db.get(Hypothesis, hid)
    if not h:
        return f"no hypothesis {hid}"
    ctx.seen_hypotheses.add(hid)
    hist = ctx.db.scalars(select(BeliefHistory).where(BeliefHistory.hypothesis_id == hid).order_by(BeliefHistory.ts, BeliefHistory.id)).all()
    ev = ctx.db.execute(select(HypothesisEvidence, Signal).join(Signal, Signal.id == HypothesisEvidence.signal_id)
                        .where(HypothesisEvidence.hypothesis_id == hid).order_by(HypothesisEvidence.contribution.desc()).limit(8)).all()
    ctx.seen_signals |= {s.id for _, s in ev}
    sk = ctx.db.scalars(select(SkepticChallenge).where(SkepticChallenge.hypothesis_id == hid)).all()
    lines = [f"H{hid}: {h.statement} | now {h.status} {h.confidence:.2f}"]
    lines += [f"  {b.ts:%Y-%m-%d} conf {b.confidence:.2f} ({b.delta:+.2f}): {b.reason[:110]}" for b in hist]
    lines += [f"  evidence S{s.id} {he.stance} contrib {he.contribution:+.2f} ({s.observed_at:%Y-%m-%d}): {s.summary[:120]}" for he, s in ev]
    lines += [f"  skeptic: {c.verdict} - {c.alternative[:120]}" for c in sk]
    return "\n".join(lines)


def t_query_signals(ctx: ChatContext, competitor=None, keywords=None, category=None, days=90, **_) -> str:
    q = select(Signal, Competitor.name).join(Competitor, Competitor.id == Signal.competitor_id).where(
        Signal.replay.is_(False), Signal.synthetic.is_(False),
        Signal.observed_at >= datetime.now(timezone.utc) - timedelta(days=int(days or 90)))
    ids, kws = _split_competitors(ctx.db, competitor, keywords)
    if ids is not None:
        q = q.where(Signal.competitor_id.in_(ids))
    if category:
        q = q.where(Signal.category == category)
    if kws:  # words may name the category/type ("pricing", "hiring") rather than appear in the summary
        q = q.where(or_(*[or_(Signal.summary.ilike(f"%{k}%"), Signal.category.ilike(f"%{k}%"), Signal.type.ilike(f"%{k}%"))
                          for k in kws]))
    rows = _rank(ctx.db.execute(q.order_by(Signal.observed_at.desc()).limit(200)).all(),
                 lambda r: f"{r[0].summary} {r[0].category} {r[0].type}", kws)[:12]
    ctx.seen_signals |= {s.id for s, _ in rows}
    return "\n".join(f"S{s.id} [{n}, {s.type}, {s.priority}, {s.observed_at:%Y-%m-%d}] {s.summary[:180]}" for s, n in rows) or "no matching signals"


def t_compare_pricing(ctx: ChatContext, competitors=None, days=365, **_) -> str:
    return t_query_signals(ctx, competitor=competitors, category="pricing", days=days)


def t_search_evidence(ctx: ChatContext, keywords=None, **_) -> str:
    ids, kws = _split_competitors(ctx.db, None, keywords)
    if not kws and not ids:
        return "give keywords"
    sig = t_query_signals(ctx, keywords=keywords, days=365)
    q = select(HypothesisEvidence, Signal).join(Signal, Signal.id == HypothesisEvidence.signal_id)
    if ids:
        q = q.where(Signal.competitor_id.in_(ids))
    if kws:
        q = q.where(or_(*[HypothesisEvidence.rationale.ilike(f"%{k}%") for k in kws]))
    rows = _rank(ctx.db.execute(q.limit(100)).all(), lambda r: r[0].rationale, kws)[:8]
    ctx.seen_signals |= {s.id for _, s in rows}
    ctx.seen_hypotheses |= {he.hypothesis_id for he, _ in rows}
    ev = "\n".join(f"H{he.hypothesis_id} <- S{s.id} ({he.stance}): {he.rationale[:150]}" for he, s in rows)
    return f"{sig}\n{ev}".strip()


TOOLS = {"list_hypotheses": t_list_hypotheses, "get_belief_history": t_get_belief_history, "query_signals": t_query_signals,
         "compare_pricing": t_compare_pricing, "search_evidence": t_search_evidence}


# ---------------- loop ----------------
def _timeline(db: Session, hid: int) -> dict:
    h = db.get(Hypothesis, hid)
    comp = db.get(Competitor, h.competitor_id)
    pts = [{"ts": b.ts.isoformat(), "confidence": b.confidence, "delta": b.delta, "reason": b.reason}
           for b in db.scalars(select(BeliefHistory).where(BeliefHistory.hypothesis_id == hid).order_by(BeliefHistory.ts, BeliefHistory.id))]
    return {"hypothesis_id": hid, "competitor": comp.name, "statement": h.statement, "status": h.status,
            "confidence": h.confidence, "band": band_label(h.confidence), "points": pts}


def answer(db: Session, question: str, history: list[dict] | None = None) -> dict:
    ctx = ChatContext(db=db)
    system = CHAT_SYSTEM.format(tools="\n".join(f"- {k}: {v}" for k, v in TOOL_DOCS.items()))
    comps = ", ".join(c.name for c in db.scalars(select(Competitor)) if not (c.notes or "").startswith("SYNTHETIC"))
    convo = "\n".join(f"{m['role'].upper()}: {m['content'][:600]}" for m in (history or [])[-6:])
    transcript: list[str] = []
    # Pre-retrieval: ground even a weak model in the hypotheses about any competitor the question names.
    names = _competitor_names(db)
    named = [n for n in names if re.search(r"\b" + re.escape(n) + r"\b", question.lower())]
    if named:
        pre = t_list_hypotheses(ctx, competitor=named)
        ctx.calls.append({"tool": "list_hypotheses", "args": {"competitor": named}, "result": pre[:500], "pre_retrieval": True})
        transcript.append(f"CALL 0 (automatic): list_hypotheses(competitor={named})\nRESULT:\n{pre[:1800]}")
    done_calls: set[str] = set()
    step = None
    for i in range(MAX_TOOL_CALLS + 1):
        forced = i == MAX_TOOL_CALLS
        user = (f"Tracked competitors: {comps}\n" + (f"Conversation so far:\n{convo}\n" if convo else "")
                + f"QUESTION: {question}\n\n" + "\n\n".join(transcript)
                + ("\n\nTool budget used up: answer now with what you have." if forced else ""))
        step = llm.complete_json(role="strong", system=system, user=user, schema=ChatStep, kind="chat",
                                 max_wait_s=20, fallback_role="fast")  # interactive: never block for minutes
        if step is None:
            rl = llm.LAST_RATE_LIMIT
            if rl.get("kind") == "chat" and time.time() - rl.get("at", 0) < 60 and rl.get("wait_s"):
                msg = (f"The LLM provider's rate limit is reached (free tier). Try again in about "
                       f"{max(1, round(rl['wait_s'] / 60))} minute(s).")
            else:
                msg = "I couldn't reach the language model (or its output was invalid). Try again shortly."
            if ctx.seen_hypotheses:  # degrade gracefully: show what the tools already found, cited
                hyps = [db.get(Hypothesis, h) for h in sorted(ctx.seen_hypotheses)]
                lines = [f"- **{h.status}** ({h.confidence:.2f}, uncalibrated): {h.statement}" for h in hyps if h][:6]
                msg += "\n\nWhat the database shows for this question:\n" + "\n".join(lines)
                cites = [{"kind": "hypothesis", "id": h.id, "label": h.statement[:160], "url": f"/hypotheses?id={h.id}",
                          "confidence": h.confidence, "status": h.status} for h in hyps if h][:6]
                return {"answer": msg, "citations": cites, "timelines": [], "tool_calls": ctx.calls, "error": True}
            return {"answer": msg, "citations": [], "timelines": [], "tool_calls": ctx.calls, "error": True}
        if step.action == "answer" or forced:
            break
        key = f"{step.action}:{sorted((step.args or {}).items())!r}"
        if key in done_calls:
            res = "ALREADY CALLED with these args: use the results above, try different args or another tool, or answer."
        else:
            done_calls.add(key)
            res = TOOLS[step.action](ctx, **(step.args or {}))
        ctx.calls.append({"tool": step.action, "args": step.args, "result": res[:500]})
        transcript.append(f"CALL {i + 1}: {step.action}({step.args})\nRESULT:\n{res[:1800]}")

    sig_ids = [s for s in dict.fromkeys(step.cited_signal_ids) if s in ctx.seen_signals]
    hyp_ids = [h for h in dict.fromkeys(step.cited_hypothesis_ids) if h in ctx.seen_hypotheses]
    dropped = (len(step.cited_signal_ids) - len(sig_ids)) + (len(step.cited_hypothesis_ids) - len(hyp_ids))
    citations = []
    for sid in sig_ids:
        s = db.get(Signal, sid)
        comp = db.get(Competitor, s.competitor_id)
        citations.append({"kind": "signal", "id": sid, "competitor": comp.name, "label": s.summary[:160],
                          "url": s.evidence_url, "observed_at": s.observed_at.isoformat()})
    for hid in hyp_ids:
        h = db.get(Hypothesis, hid)
        citations.append({"kind": "hypothesis", "id": hid, "label": h.statement[:160], "url": f"/hypotheses?id={hid}",
                          "confidence": h.confidence, "status": h.status})
    used_history = {int(re.search(r"\d+", str(c["args"].get("hypothesis_id", 0))).group())
                    for c in ctx.calls if c["tool"] == "get_belief_history" and re.search(r"\d+", str(c["args"].get("hypothesis_id", "")))}
    timelines = [_timeline(db, hid) for hid in hyp_ids if hid in used_history and db.get(Hypothesis, hid)][:3]
    # gpt-oss adds its own 【n】/[^n] markers that point at nothing in our data; real sources are in `citations`
    text = re.sub(r"\s*(【[^】]*】|\[\^\d+\])", "", step.answer or "").strip()
    return {"answer": text or "(no answer produced)", "citations": citations, "timelines": timelines,
            "tool_calls": ctx.calls, "dropped_citations": dropped, "error": False}
