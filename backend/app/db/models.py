"""SQLAlchemy 2 models. SQLite today; kept Postgres-compatible (JSON, no SQLite-only types)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Competitor(Base):
    __tablename__ = "competitors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    domain: Mapped[str] = mapped_column(String(255))
    pricing_url: Mapped[str | None] = mapped_column(String(500))
    product_urls: Mapped[list[Any]] = mapped_column(JSON, default=list)
    careers_provider: Mapped[str | None] = mapped_column(String(20))  # greenhouse | lever | None
    careers_token: Mapped[str | None] = mapped_column(String(120))
    news_query: Mapped[str | None] = mapped_column(String(255))
    feed_urls: Mapped[list[Any]] = mapped_column(JSON, default=list)  # company blog / changelog RSS/Atom
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    sources: Mapped[list["Source"]] = relationship(back_populates="competitor", cascade="all, delete-orphan")


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"))
    source_type: Mapped[str] = mapped_column(String(20))  # page | jobs | news | early_signal
    url: Mapped[str] = mapped_column(String(1000))
    check_interval_min: Mapped[int] = mapped_column(Integer, default=720)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(200))

    competitor: Mapped[Competitor] = relationship(back_populates="sources")


class Snapshot(Base):
    __tablename__ = "snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_text: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Signal(Base):
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    type: Mapped[str] = mapped_column(String(40))
    category: Mapped[str] = mapped_column(String(20))  # pricing | product | hiring | market | early_signal
    summary: Mapped[str] = mapped_column(Text)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    evidence_url: Mapped[str] = mapped_column(String(1000))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # when it was publicly true
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # when we saw it
    origin_group: Mapped[str] = mapped_column(String(120))
    event_confidence: Mapped[float] = mapped_column(Float, default=0.9)
    priority: Mapped[str] = mapped_column(String(10), default="low")
    dedup_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    replay: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("ix_signals_comp_observed", "competitor_id", "observed_at"),
        Index("ix_signals_origin_group", "origin_group"),
    )


class Hypothesis(Base):
    __tablename__ = "hypotheses"
    id: Mapped[int] = mapped_column(primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"), index=True)
    statement: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="emerging")
    confidence: Mapped[float] = mapped_column(Float)  # interpretation_confidence (displayed)
    prior: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    testable_predictions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    evidence_needed: Mapped[list[Any]] = mapped_column(JSON, default=list)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    replay: Mapped[bool] = mapped_column(Boolean, default=False)


class HypothesisEvidence(Base):
    __tablename__ = "hypothesis_evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    hypothesis_id: Mapped[int] = mapped_column(ForeignKey("hypotheses.id", ondelete="CASCADE"), index=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id", ondelete="CASCADE"))
    stance: Mapped[str] = mapped_column(String(12))  # supports | contradicts | neutral
    relevance: Mapped[float] = mapped_column(Float)
    reliability: Mapped[float] = mapped_column(Float)
    independence_weight: Mapped[float] = mapped_column(Float, default=1.0)
    contribution: Mapped[float] = mapped_column(Float, default=0.0)
    rationale: Mapped[str] = mapped_column(Text)
    added_by: Mapped[str] = mapped_column(String(20))  # strategist | investigator | skeptic
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BeliefHistory(Base):
    __tablename__ = "belief_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    hypothesis_id: Mapped[int] = mapped_column(ForeignKey("hypotheses.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confidence: Mapped[float] = mapped_column(Float)
    delta: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)

    __table_args__ = (Index("ix_belief_hyp_ts", "hypothesis_id", "ts"),)


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[int] = mapped_column(primary_key=True)
    hypothesis_id: Mapped[int] = mapped_column(ForeignKey("hypotheses.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    plan: Mapped[list[Any]] = mapped_column(JSON, default=list)
    actions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    findings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    stop_reason: Mapped[str | None] = mapped_column(String(200))
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class SkepticChallenge(Base):
    __tablename__ = "skeptic_challenges"
    id: Mapped[int] = mapped_column(primary_key=True)
    hypothesis_id: Mapped[int] = mapped_column(ForeignKey("hypotheses.id", ondelete="CASCADE"), index=True)
    alternative: Mapped[str] = mapped_column(Text)
    discriminating_test: Mapped[str] = mapped_column(Text)
    test_result: Mapped[str | None] = mapped_column(Text)
    verdict: Mapped[str] = mapped_column(String(30), default="pending")
    # alternative_supported | alternative_refuted | inconclusive | pending
    evidence_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(primary_key=True)
    hypothesis_id: Mapped[int] = mapped_column(ForeignKey("hypotheses.id", ondelete="CASCADE"), index=True)
    claim: Mapped[str] = mapped_column(Text)
    made_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    horizon_days: Mapped[int] = mapped_column(Integer)
    resolve_by: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confidence_at_creation: Mapped[float] = mapped_column(Float)
    outcome: Mapped[str] = mapped_column(String(10), default="open")  # open | hit | miss | expired
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id", ondelete="SET NULL"))


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"))
    hypothesis_id: Mapped[int | None] = mapped_column(ForeignKey("hypotheses.id", ondelete="SET NULL"))
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id", ondelete="SET NULL"))
    priority: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    channel: Mapped[str | None] = mapped_column(String(20))
    feedback: Mapped[str | None] = mapped_column(String(20))


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tool_calls: Mapped[list[Any]] = mapped_column(JSON, default=list)
    model: Mapped[str | None] = mapped_column(String(120))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text)


class EvalRun(Base):
    __tablename__ = "eval_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    contamination_mode: Mapped[str] = mapped_column(String(20))


class EvalEvent(Base):
    __tablename__ = "eval_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    eval_run_id: Mapped[int] = mapped_column(ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True)
    competitor: Mapped[str] = mapped_column(String(120))
    event_label: Mapped[str] = mapped_column(Text)
    public_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    category: Mapped[str] = mapped_column(String(20))
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lead_days: Mapped[float | None] = mapped_column(Float)
    matched_hypothesis_id: Mapped[int | None] = mapped_column(Integer)
    is_true_positive: Mapped[bool] = mapped_column(Boolean, default=False)


class UserFeedback(Base):
    __tablename__ = "user_feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"))
    useful: Mapped[bool] = mapped_column(Boolean)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentCursor(Base):
    """Highest signal id the strategist has already reviewed, per competitor (avoids re-reading the feed)."""
    __tablename__ = "agent_cursors"
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"), primary_key=True)
    last_signal_id: Mapped[int] = mapped_column(Integer, default=0)
    memory_note: Mapped[str | None] = mapped_column(Text)  # strategist's one-line note for the next cycle
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
