"""Pydantic contracts for every agent output. Invalid output -> one retry -> skipped (see llm.py)."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.agents.tools import TOOL_NAMES

Stance = Literal["supports", "contradicts", "neutral"]
HypCategory = Literal["pricing", "product", "hiring", "market"]
SIGNAL_TYPES = ["price_change", "plan_change", "feature_launch", "positioning_change", "removal", "funding",
                "partnership", "acquisition", "news_mention", "hiring_spike", "hiring_new_location",
                "hiring_tech_keyword", "new_subdomain", "new_sitemap_path", "investigation_finding"]
USABLE_TOOLS = tuple(t for t in TOOL_NAMES if t != "web_search")


# ---------------- strategist ----------------
class EvidenceLink(BaseModel):
    hypothesis_id: int
    signal_id: int
    stance: Stance
    relevance: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=5, max_length=300)


class NewLink(BaseModel):
    signal_id: int
    stance: Stance
    relevance: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=5, max_length=300)


class TestablePrediction(BaseModel):
    claim: str = Field(min_length=10, max_length=300)
    horizon_days: int = Field(ge=7, le=365)
    signal_types: list[str] = Field(min_length=1, max_length=4)
    keywords: list[str] = Field(min_length=1, max_length=6)

    @field_validator("signal_types")
    @classmethod
    def known_types(cls, v: list[str]) -> list[str]:
        """Drop unknown types (one bad type shouldn't discard a whole strategist run); need >= 1 known."""
        kept = [t for t in v if t in SIGNAL_TYPES]
        if not kept:
            raise ValueError(f"no known signal types in {v}; use only {SIGNAL_TYPES}")
        return kept


class NewHypothesis(BaseModel):
    statement: str = Field(min_length=15, max_length=300)
    category: HypCategory
    links: list[NewLink] = Field(min_length=1, max_length=12)
    testable_predictions: list[TestablePrediction] = Field(min_length=1, max_length=3)
    evidence_needed: list[str] = Field(default_factory=list, max_length=5)


class StrategistOut(BaseModel):
    same_event_groups: list[list[int]] = Field(default_factory=list, max_length=10)  # signal ids reporting ONE event
    links: list[EvidenceLink] = Field(default_factory=list)
    new_hypotheses: list[NewHypothesis] = Field(default_factory=list, max_length=2)
    memory_note: str = Field(default="", max_length=400)


# ---------------- investigator ----------------
class Finding(BaseModel):
    signal_id: int | None = None  # an existing signal returned by a tool
    url: str | None = None  # or a URL a tool returned
    summary: str = Field(min_length=5, max_length=300)
    stance: Stance
    relevance: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def cites_something(self):
        if self.signal_id is None and not self.url:
            raise ValueError("a finding must cite a signal_id or a url returned by a tool")
        return self


class InvestigatorStep(BaseModel):
    plan: list[str] = Field(default_factory=list, max_length=4)  # sentences, e.g. "Check jobs for ML infra roles"
    observation: str = Field(default="", max_length=500)  # what the last tool result changed
    findings: list[Finding] = Field(default_factory=list, max_length=6)

    @field_validator("findings", mode="before")
    @classmethod
    def drop_uncited(cls, v):
        """A finding citing nothing (e.g. "no relevant results") is dropped on its own instead of failing the
        whole step; cited findings are still validated (and checked against tool output later)."""
        if not isinstance(v, list):
            return v
        return [f for f in v if not isinstance(f, dict) or f.get("signal_id") is not None or f.get("url")]
    action: Literal[USABLE_TOOLS + ("stop",)] = "stop"  # type: ignore[valid-type]  # omitted action = stop
    args: dict[str, Any] = Field(default_factory=dict)
    stop_reason: str | None = None


# ---------------- skeptic ----------------
MERE_DISAGREEMENT = re.compile(
    r"^\s*(the )?(hypothesis|claim|this)\s+(is|may be|might be|could be)\s+(wrong|incorrect|false|unproven|unsupported|not true)",
    re.I)


class DiscriminatingTest(BaseModel):
    tool: Literal[USABLE_TOOLS]  # type: ignore[valid-type]
    args: dict[str, Any] = Field(default_factory=dict)
    favors_alternative_if: str = Field(min_length=3, max_length=400)
    favors_hypothesis_if: str = Field(min_length=3, max_length=400)


class Alternative(BaseModel):
    alternative: str = Field(min_length=25, max_length=400)
    discriminating_test: DiscriminatingTest

    @field_validator("alternative")
    @classmethod
    def not_mere_disagreement(cls, v: str) -> str:
        if MERE_DISAGREEMENT.search(v):
            raise ValueError("mere disagreement is invalid: name a concrete mundane mechanism that would produce the same observations")
        return v


class SkepticOut(BaseModel):
    alternatives: list[Alternative] = Field(min_length=2, max_length=3)


class Verdict(BaseModel):
    index: int
    verdict: Literal["alternative_supported", "alternative_refuted", "inconclusive"]
    test_result: str = Field(min_length=5, max_length=400)
    cited_urls: list[str] = Field(default_factory=list, max_length=5)
    cited_signal_ids: list[int] = Field(default_factory=list, max_length=5)


class VerdictsOut(BaseModel):
    verdicts: list[Verdict] = Field(min_length=1, max_length=3)
