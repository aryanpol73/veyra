"""Deterministic, independence-aware belief engine (the Judge's maths). No LLM anywhere here.

    confidence = sigmoid( logit(prior) + sum(contributions) + skeptic_adjustment )

    contribution_i = stance_sign * relevance * source_reliability * event_confidence
                     * recency_decay * independence_weight * K

  * recency_decay     = 0.5 ** (age_days / half_life[signal category])
  * independence      = per origin_group, the strongest item counts 1.0, the rest 0.2 each
                        (three articles about one press release are not three signals)
  * category cap      = |sum of contributions| per signal category is clipped to CATEGORY_CAP
  * skeptic           = each surviving alternative (alternative_supported) subtracts SKEPTIC_SURVIVES;
                        each refuted alternative adds a small SKEPTIC_REFUTED

Three confidences are kept apart (see README): event_confidence lives on a signal,
interpretation_confidence is what this module computes, prediction_confidence is stored on predictions.
The output is an UNCALIBRATED heuristic score until the evaluation page shows calibration.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

K = 1.2
SAME_GROUP_WEIGHT = 0.2
CATEGORY_CAP = 2.5  # logit units
SKEPTIC_SURVIVES = 0.6
SKEPTIC_REFUTED = 0.15

PRIOR = {"pricing": 0.2, "product": 0.2, "hiring": 0.2, "market": 0.15}
HALF_LIFE_DAYS = {"pricing": 90, "product": 60, "hiring": 45, "market": 60, "early_signal": 21}
SOURCE_RELIABILITY = {"official": 1.0, "news": 0.7, "aggregator": 0.4, "early_signal": 0.35, "archive": 0.9}
STANCE_SIGN = {"supports": 1.0, "contradicts": -1.0, "neutral": 0.0}

REPUTABLE_NEWS = ("techcrunch", "theverge", "reuters", "bloomberg", "wsj", "ft.com", "cnbc", "venturebeat",
                  "forbes", "businessinsider", "zdnet", "wired", "theinformation", "axios", "nytimes", "infoworld",
                  "siliconangle", "geekwire", "protocol", "arstechnica", "engadget", "fastcompany")


@dataclass(frozen=True)
class EvidenceItem:
    id: int
    stance: str  # supports | contradicts | neutral
    relevance: float  # 0..1 (from the strategist / investigator)
    reliability: float  # 0..1 (from source_reliability())
    event_confidence: float  # 0..1 (on the signal)
    observed_at: datetime
    origin_group: str
    category: str  # signal category, drives half-life + cap


@dataclass
class BeliefResult:
    confidence: float
    logit: float
    contributions: dict[int, float] = field(default_factory=dict)
    independence: dict[int, float] = field(default_factory=dict)
    capped_categories: list[str] = field(default_factory=list)


def logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def recency_decay(observed_at: datetime, now: datetime, category: str) -> float:
    age = max((now - observed_at).total_seconds() / 86400, 0.0)
    return 0.5 ** (age / HALF_LIFE_DAYS.get(category, 60))


def source_reliability(source_type: str | None, raw: dict, evidence_url: str = "", competitor_domain: str = "") -> float:
    """Map a signal's provenance to a reliability weight."""
    url = (evidence_url or "").lower()
    if source_type in ("page", "jobs"):
        return SOURCE_RELIABILITY["official"]
    if source_type == "early_signal":
        return SOURCE_RELIABILITY["early_signal"]
    if source_type == "news":
        if raw.get("kind") == "blog":
            return SOURCE_RELIABILITY["official"]
        return SOURCE_RELIABILITY["news"] if any(r in url for r in REPUTABLE_NEWS) else SOURCE_RELIABILITY["aggregator"]
    # investigator findings: judge by where the evidence lives
    if "web.archive.org" in url:
        return SOURCE_RELIABILITY["archive"]
    if competitor_domain and competitor_domain in url or "greenhouse.io" in url or "lever.co" in url:
        return SOURCE_RELIABILITY["official"]
    return SOURCE_RELIABILITY["aggregator"]


def _raw(e: EvidenceItem, now: datetime) -> float:
    return (STANCE_SIGN.get(e.stance, 0.0) * e.relevance * e.reliability * e.event_confidence
            * recency_decay(e.observed_at, now, e.category) * K)


def score(prior: float, items: list[EvidenceItem], now: datetime,
          skeptic_verdicts: list[str] | None = None) -> BeliefResult:
    res = BeliefResult(confidence=prior, logit=logit(prior))
    # 1) independence weighting within each origin group (strongest first counts fully)
    groups: dict[str, list[tuple[EvidenceItem, float]]] = defaultdict(list)
    for e in items:
        groups[e.origin_group].append((e, _raw(e, now)))
    weighted: dict[int, tuple[EvidenceItem, float]] = {}
    for members in groups.values():
        members.sort(key=lambda m: abs(m[1]), reverse=True)
        for rank, (e, c) in enumerate(members):
            w = 1.0 if rank == 0 else SAME_GROUP_WEIGHT
            res.independence[e.id] = w
            weighted[e.id] = (e, c * w)
    # 2) per-category cap (scale every item in an over-cap category proportionally)
    by_cat: dict[str, float] = defaultdict(float)
    for e, c in weighted.values():
        by_cat[e.category] += c
    scale = {}
    for cat, total in by_cat.items():
        if abs(total) > CATEGORY_CAP:
            scale[cat] = CATEGORY_CAP / abs(total)
            res.capped_categories.append(cat)
    total = 0.0
    for eid, (e, c) in weighted.items():
        c *= scale.get(e.category, 1.0)
        res.contributions[eid] = c
        total += c
    # 3) skeptic adjustments
    for v in skeptic_verdicts or []:
        if v == "alternative_supported":
            total -= SKEPTIC_SURVIVES
        elif v == "alternative_refuted":
            total += SKEPTIC_REFUTED
    res.logit = logit(prior) + total
    res.confidence = sigmoid(res.logit)
    return res


def status_for(confidence: float, *, max_confidence_seen: float, has_primary_support: bool,
               has_contradiction: bool) -> str:
    """emerging < 0.4 <= plausible < 0.7 <= likely < 0.9 <= confirmed (needs direct primary evidence)."""
    if confidence < 0.1 and has_contradiction:
        return "refuted"
    if confidence < 0.2 and max_confidence_seen >= 0.4:
        return "stale"
    if confidence >= 0.9:
        return "confirmed" if has_primary_support else "likely"
    if confidence >= 0.7:
        return "likely"
    if confidence >= 0.4:
        return "plausible"
    return "emerging"


def band_label(confidence: float) -> str:
    return ("Confirmed" if confidence >= 0.9 else "Likely" if confidence >= 0.7
            else "Plausible" if confidence >= 0.4 else "Emerging")
