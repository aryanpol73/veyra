"""Daily brief: What happened / Why it matters / What to do, with evidence links and confidence caveats.

Selection is deterministic (what changed since `since`): new/raised alerts, hypotheses whose confidence moved
>= MIN_DELTA, and critical/high signals. One LLM call (reporter) writes the prose for at most MAX_ITEMS items;
without an LLM a plain template is used. Facts, dates, links and confidence numbers always come from the DB.
Saved as Markdown in data/reports/brief_<date>.md; optionally posted to a Slack incoming webhook.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import llm
from app.agents import prompts
from app.belief.engine import band_label
from app.config import DATA_DIR, get_settings
from app.db.models import Alert, BeliefHistory, Competitor, Hypothesis, HypothesisEvidence, Signal, SkepticChallenge

log = logging.getLogger("veyra.brief")
REPORTS_DIR = DATA_DIR / "reports"
MAX_ITEMS = 6
MIN_DELTA = 0.05
CAVEAT = "uncalibrated heuristic score"


class BriefItemText(BaseModel):
    index: int
    what_happened: str = Field(max_length=700)
    why_it_matters: str = Field(max_length=700)
    what_to_do: str = Field(max_length=500)


class BriefText(BaseModel):
    headline: str = Field(max_length=200)
    items: list[BriefItemText] = Field(default_factory=list, max_length=MAX_ITEMS)


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def gather(db: Session, since: datetime) -> list[dict]:
    """Deterministic: which hypotheses / signals belong in today's brief, with their facts."""
    items: list[dict] = []
    seen_h: set[int] = set()
    shown_signals: set[int] = set()  # evidence already shown under a hypothesis isn't repeated as its own item
    live = Hypothesis.replay.is_(False) & Hypothesis.synthetic.is_(False)
    moved: dict[int, float] = {}
    for b in db.scalars(select(BeliefHistory).join(Hypothesis).where(BeliefHistory.ts >= since, live)):
        moved[b.hypothesis_id] = moved.get(b.hypothesis_id, 0.0) + b.delta
    alerted = {a.hypothesis_id for a in db.scalars(select(Alert).where(Alert.created_at >= since, Alert.hypothesis_id.is_not(None)))}
    cands = [db.get(Hypothesis, hid) for hid in set(moved) | alerted]
    cands = [h for h in cands if h and (h.id in alerted or abs(moved.get(h.id, 0)) >= MIN_DELTA)]
    cands.sort(key=lambda h: (h.id not in alerted, -abs(moved.get(h.id, 0))))
    for h in cands[:MAX_ITEMS]:
        comp = db.get(Competitor, h.competitor_id)
        ev = db.execute(select(HypothesisEvidence, Signal).join(Signal, Signal.id == HypothesisEvidence.signal_id)
                        .where(HypothesisEvidence.hypothesis_id == h.id, HypothesisEvidence.stance == "supports")
                        .order_by(HypothesisEvidence.contribution.desc()).limit(3)).all()
        sk = db.scalars(select(SkepticChallenge).where(SkepticChallenge.hypothesis_id == h.id)).all()
        strongest = next((c for c in sk if c.verdict == "alternative_supported"), None) or next(
            (c for c in sk if c.verdict == "inconclusive"), None)
        items.append({"kind": "hypothesis", "competitor": comp.name, "hypothesis_id": h.id, "statement": h.statement,
                      "status": h.status, "confidence": h.confidence, "delta": round(moved.get(h.id, 0.0), 2),
                      "alerted": h.id in alerted,
                      "evidence": [{"summary": s.summary, "url": s.evidence_url, "date": f"{s.observed_at:%Y-%m-%d}"} for _, s in ev],
                      "strongest_alternative": (f"{strongest.alternative} ({strongest.verdict.replace('_', ' ')})" if strongest else None)})
        seen_h.add(h.id)
        shown_signals |= {s.id for _, s in ev}
    room = MAX_ITEMS - len(items)
    if room > 0:
        sigs = db.scalars(select(Signal).where(Signal.detected_at >= since, Signal.priority.in_(["critical", "high"]),
                                               Signal.replay.is_(False), Signal.synthetic.is_(False))
                          .order_by(Signal.priority, Signal.observed_at.desc()).limit(room + len(shown_signals))).all()
        for s in [x for x in sigs if x.id not in shown_signals][:room]:
            comp = db.get(Competitor, s.competitor_id)
            items.append({"kind": "signal", "competitor": comp.name, "signal_id": s.id, "type": s.type, "priority": s.priority,
                          "summary": s.summary, "url": s.evidence_url, "date": f"{s.observed_at:%Y-%m-%d}",
                          "early_signal": s.category == "early_signal"})
    return items


def _facts(i: int, it: dict) -> str:
    if it["kind"] == "hypothesis":
        ev = "; ".join(f"{e['date']} {e['summary'][:140]}" for e in it["evidence"])
        return (f"[{i}] {it['competitor']} hypothesis: {it['statement']} | {it['status']} {it['confidence']:.2f} "
                f"(moved {it['delta']:+.2f}{', alerted' if it['alerted'] else ''}) | evidence: {ev} | strongest "
                f"alternative: {it['strongest_alternative'] or 'not yet challenged'}")
    return f"[{i}] {it['competitor']} {it['priority']} {it['type']} on {it['date']}: {it['summary']}" + (
        " (early signal: a lead, not proof)" if it["early_signal"] else "")


def _template(it: dict) -> BriefItemText:
    if it["kind"] == "hypothesis":
        return BriefItemText(index=0, what_happened=f"Evidence moved the hypothesis \"{it['statement']}\" by {it['delta']:+.2f}.",
                             why_it_matters="It is a working hypothesis about the competitor's strategy; see the evidence below.",
                             what_to_do="Review the evidence and the skeptic's alternative before acting.")
    return BriefItemText(index=0, what_happened=it["summary"], why_it_matters="Flagged by the priority rules.",
                         what_to_do="Check the evidence link.")


def render(items: list[dict], text: BriefText | None, day: str, used_llm: bool) -> str:
    lines = [f"# Veyra daily brief: {day}", ""]
    lines.append(f"_{text.headline}_" if text and text.headline else "_No narrative available (template mode)._")
    lines += ["", f"Confidence numbers are an **{CAVEAT}**, not validated probabilities."
              + ("" if used_llm else " Narrative written by template (no LLM)."), ""]
    if not items:
        lines.append("Nothing crossed the brief threshold since the last brief.")
    by_idx = {t.index: t for t in (text.items if text else [])}
    for i, it in enumerate(items):
        t = by_idx.get(i) or _template(it)
        if it["kind"] == "hypothesis":
            lines += [f"## {i + 1}. {it['competitor']}: {it['statement']}",
                      f"**{band_label(it['confidence'])} {it['confidence']:.2f}** ({it['status']}, {it['delta']:+.2f} since last brief, {CAVEAT})"
                      + (" · **alerted**" if it["alerted"] else "")]
        else:
            lines += [f"## {i + 1}. {it['competitor']}: {it['type'].replace('_', ' ')} ({it['priority']})"
                      + (" · Early Signal" if it["early_signal"] else "")]
        lines += ["", f"**What happened.** {t.what_happened}", "", f"**Why it matters.** {t.why_it_matters}", "",
                  f"**What to do.** {t.what_to_do}", ""]
        if it["kind"] == "hypothesis":
            lines += ["Evidence:"] + [f"- {e['date']}: [{e['summary'][:140]}]({e['url']})" for e in it["evidence"]]
            lines += ["", f"Strongest alternative: {it['strongest_alternative'] or 'not yet challenged by the skeptic'}", ""]
        else:
            lines += [f"Evidence: [{it['date']}]({it['url']})", ""]
    return "\n".join(lines)


def generate(db: Session, *, since: datetime | None = None, now: datetime | None = None, post: bool = False) -> dict:
    now = now or datetime.now(timezone.utc)
    since = since or now - timedelta(days=1)
    items = gather(db, since)
    text = None
    if items and get_settings().llm_configured:
        facts = "\n".join(_facts(i, it) for i, it in enumerate(items))
        text = llm.complete_json(role="strong", system=prompts.REPORTER, user=f"Items:\n{facts}", schema=BriefText, kind="reporter",
                                 max_wait_s=30, fallback_role="fast")  # interactive: template fallback beats a long wait
    day = f"{now:%Y-%m-%d}"
    md = render(items, text, day, used_llm=text is not None)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"brief_{day}.md"
    path.write_text(md, "utf-8")
    delivered = None
    if post and get_settings().slack_webhook_url:
        try:
            r = httpx.post(get_settings().slack_webhook_url, json={"text": md[:3500]}, timeout=15)
            delivered = r.status_code < 300
        except httpx.HTTPError as e:
            log.warning("slack delivery failed: %s", e)
            delivered = False
    return {"date": day, "path": str(path), "items": len(items), "used_llm": text is not None, "delivered_slack": delivered,
            "markdown": md}


def list_reports() -> list[dict]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return [{"date": p.stem.removeprefix("brief_"), "bytes": p.stat().st_size}
            for p in sorted(REPORTS_DIR.glob("brief_*.md"), reverse=True)]


def read_report(day: str) -> str | None:
    p = REPORTS_DIR / f"brief_{day}.md"
    return p.read_text("utf-8") if p.exists() and p.parent == REPORTS_DIR else None
