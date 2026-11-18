"""Signal drafts -> priority (rule table) -> origin groups -> dedup -> `signals` rows."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import sha
from app.db.models import Signal

CATEGORY_OF = {
    "price_change": "pricing", "plan_change": "pricing",
    "feature_launch": "product", "removal": "product",
    "positioning_change": "market", "funding": "market", "partnership": "market",
    "acquisition": "market", "news_mention": "market",
    "hiring_spike": "hiring", "hiring_new_location": "hiring", "hiring_tech_keyword": "hiring",
    "new_subdomain": "early_signal", "new_sitemap_path": "early_signal",
    "investigation_finding": "product",  # category overridden by the hypothesis it was found for
}

# Thresholds are deliberately simple and visible; tune here.
PRIORITY_RULES = {
    "price_change_critical_pct": 0.20,
    "hiring_spike_z_high": 2.0,
    "interesting_path": re.compile(r"(pricing|enterprise|ai|agent|llm|security|compliance|partners?)", re.I),
}


@dataclass
class SignalDraft:
    type: str
    summary: str
    evidence_url: str
    observed_at: datetime
    dedup_basis: str
    event_confidence: float
    old_value: str | None = None
    new_value: str | None = None
    origin_group: str | None = None  # None -> its own group
    category: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def priority_for(d: SignalDraft) -> str:
    t, raw = d.type, d.raw
    if t == "price_change":
        pct = raw.get("price_pct")
        return "critical" if pct is not None and pct > PRIORITY_RULES["price_change_critical_pct"] else "high"
    if t in ("plan_change", "acquisition", "funding"):
        return "high"
    if t == "removal":
        return "high" if (d.category or CATEGORY_OF[t]) == "pricing" else "medium"
    if t == "hiring_spike":
        return "high" if raw.get("z", 0) > PRIORITY_RULES["hiring_spike_z_high"] else "medium"
    if t in ("feature_launch", "partnership", "hiring_tech_keyword", "hiring_new_location"):
        return "medium"
    if t == "positioning_change":
        return "medium"
    if t == "new_subdomain":
        return "medium" if PRIORITY_RULES["interesting_path"].search(d.new_value or "") else "low"
    if t == "new_sitemap_path":
        return "medium" if PRIORITY_RULES["interesting_path"].search(d.new_value or "") else "low"
    return "low"  # news_mention, copy tweaks


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def assign_news_group(db: Session, competitor_id: int, title: str, observed_at: datetime, threshold: float = 0.4) -> str | None:
    """Several articles about one announcement share an origin_group (independence weighting later)."""
    window = observed_at - timedelta(days=10)
    recent = db.scalars(select(Signal).where(
        Signal.competitor_id == competitor_id, Signal.observed_at >= window,
        Signal.type.in_(["news_mention", "funding", "partnership", "acquisition", "feature_launch", "plan_change"]),
    )).all()
    best, best_sim = None, threshold
    for s in recent:
        sim = jaccard(title, s.raw.get("title", s.summary))
        if sim >= best_sim:
            best, best_sim = s.origin_group, sim
    return best


def persist(db: Session, competitor_id: int, source_id: int | None, drafts: list[SignalDraft],
            *, synthetic: bool = False, replay: bool = False, detected_at: datetime | None = None) -> list[Signal]:
    """Insert new signals; skip duplicates by dedup_key. Returns the inserted rows."""
    out: list[Signal] = []
    for d in drafts:
        key = sha(f"{competitor_id}|{d.type}|{d.dedup_basis}")[:64]
        if db.scalar(select(Signal.id).where(Signal.dedup_key == key)):
            continue
        group = d.origin_group or f"{d.type}:{key[:12]}"
        s = Signal(
            competitor_id=competitor_id, source_id=source_id, type=d.type,
            category=d.category or CATEGORY_OF.get(d.type, "market"), summary=d.summary,
            old_value=d.old_value, new_value=d.new_value, evidence_url=d.evidence_url,
            observed_at=d.observed_at, origin_group=group, event_confidence=d.event_confidence,
            priority=priority_for(d), dedup_key=key, raw=d.raw, synthetic=synthetic, replay=replay,
            **({"detected_at": detected_at} if detected_at else {}),
        )
        db.add(s)
        db.flush()
        out.append(s)
    return out
