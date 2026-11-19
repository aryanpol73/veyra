"""Chat grounding and brief generation, with a scripted fake LLM (no network)."""
from datetime import datetime, timedelta, timezone

import pytest

NOW = datetime.now(timezone.utc)


@pytest.fixture()
def db():
    from app.db.models import Base, BeliefHistory, Competitor, Hypothesis, HypothesisEvidence, Signal
    from app.db.session import SessionLocal, engine

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    s = SessionLocal()
    s.add(Competitor(id=1, name="Acme", domain="acme.example", product_urls=[]))
    s.flush()
    s.add_all([Signal(id=1, competitor_id=1, type="plan_change", category="pricing", summary="Acme adds usage-based credits plan",
                      evidence_url="https://acme.example/pricing", observed_at=NOW - timedelta(days=5), detected_at=NOW - timedelta(hours=3),
                      origin_group="g1", event_confidence=0.95, priority="high", raw={}),
               Signal(id=2, competitor_id=1, type="price_change", category="pricing", summary="Acme raises Pro by 30%",
                      evidence_url="https://acme.example/pricing#pro", observed_at=NOW - timedelta(days=1), detected_at=NOW - timedelta(hours=2),
                      origin_group="g2", event_confidence=0.95, priority="critical", raw={})])
    s.add(Hypothesis(id=1, competitor_id=1, statement="Acme is moving to usage-based pricing", category="pricing",
                     status="plausible", confidence=0.62, prior=0.2, created_at=NOW - timedelta(days=10)))
    s.flush()
    s.add(HypothesisEvidence(hypothesis_id=1, signal_id=1, stance="supports", relevance=0.9, reliability=1.0,
                             contribution=0.9, rationale="credits plan is usage-based", added_by="strategist"))
    s.add_all([BeliefHistory(hypothesis_id=1, ts=NOW - timedelta(days=10), confidence=0.2, delta=0, reason="created"),
               BeliefHistory(hypothesis_id=1, ts=NOW - timedelta(hours=1), confidence=0.62, delta=0.42, reason="credits plan")])
    s.commit()
    yield s
    s.close()


def script(monkeypatch, steps):
    from app import llm

    it = iter(steps)
    monkeypatch.setattr(llm, "complete_json", lambda **kw: kw["schema"].model_validate(next(it)))


def test_chat_cites_only_what_tools_returned_and_builds_timeline_from_db(db, monkeypatch):
    from app.agents.chat import answer

    script(monkeypatch, [
        {"action": "list_hypotheses", "args": {"competitor": "Acme"}},
        {"action": "get_belief_history", "args": {"hypothesis_id": "H1"}},
        {"action": "answer", "answer": "Confidence rose from 0.20 to 0.62 after the credits plan.",
         "cited_signal_ids": ["S1", 999], "cited_hypothesis_ids": [1, 42]},
    ])
    out = answer(db, "How has Acme's pricing strategy evolved?")
    assert [c["id"] for c in out["citations"] if c["kind"] == "signal"] == [1]
    assert [c["id"] for c in out["citations"] if c["kind"] == "hypothesis"] == [1]
    assert out["dropped_citations"] == 2  # S999 and H42 were never returned by a tool
    tl = out["timelines"][0]
    assert tl["hypothesis_id"] == 1 and [p["confidence"] for p in tl["points"]] == [0.2, 0.62]  # numbers from the DB
    # call 0 is the automatic pre-retrieval for the named competitor, then the model's own calls
    assert [c["tool"] for c in out["tool_calls"]] == ["list_hypotheses", "list_hypotheses", "get_belief_history"]
    assert out["tool_calls"][0].get("pre_retrieval") is True


def test_search_splits_phrases_and_competitor_names(db):
    from app.agents.chat import ChatContext, t_query_signals, t_search_evidence

    ctx = ChatContext(db=db)
    assert "S1" in t_query_signals(ctx, keywords=["Acme pricing strategy evolution"])  # phrase matched verbatim nothing
    assert "S1" in t_search_evidence(ctx, keywords=["Acme credits"])


def test_repeated_tool_call_is_not_rerun(db, monkeypatch):
    from app.agents import chat

    script(monkeypatch, [{"action": "query_signals", "args": {"keywords": ["x"]}},
                         {"action": "query_signals", "args": {"keywords": ["x"]}},
                         {"action": "answer", "answer": "done"}])
    out = chat.answer(db, "anything?")
    assert out["tool_calls"][1]["result"].startswith("ALREADY CALLED")


def test_chat_tool_budget_forces_an_answer(db, monkeypatch):
    from app.agents import chat

    script(monkeypatch, [{"action": "query_signals", "args": {}}] * chat.MAX_TOOL_CALLS + [
        {"action": "query_signals", "answer": "Best effort answer.", "cited_signal_ids": [2]}])
    out = chat.answer(db, "anything new?")
    assert len(out["tool_calls"]) == chat.MAX_TOOL_CALLS and out["answer"] == "Best effort answer."


def test_brief_template_mode(db, monkeypatch, tmp_path):
    from app.config import get_settings
    from app.reports import brief

    monkeypatch.setattr(brief, "REPORTS_DIR", tmp_path / "reports")
    assert not get_settings().llm_configured  # tests run without an LLM key
    out = brief.generate(db, since=NOW - timedelta(days=1))
    md = out["markdown"]
    assert out["items"] == 2 and not out["used_llm"]
    assert "Acme is moving to usage-based pricing" in md and "uncalibrated heuristic score" in md
    assert "https://acme.example/pricing" in md and "price change (critical)" in md
    assert brief.read_report(out["date"]) == md


def test_chat_degrades_to_tool_results_when_llm_fails(db, monkeypatch):
    from app import llm
    from app.agents import chat

    calls = iter([chat.ChatStep(action="list_hypotheses", args={}), None])
    monkeypatch.setattr(llm, "complete_json", lambda **kw: next(calls))
    out = chat.answer(db, "what about Acme?")
    assert out["error"] and "usage-based pricing" in out["answer"] and out["citations"][0]["id"] == 1
