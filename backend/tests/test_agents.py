"""Agent guardrails that must hold regardless of what the LLM says."""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.agents.schemas import Finding, SkepticOut, TestablePrediction

NOW = datetime(2026, 11, 18, tzinfo=timezone.utc)
TEST = {"tool": "search_jobs", "args": {"keywords": ["ML"]},
        "favors_alternative_if": "few roles and all are backfills", "favors_hypothesis_if": "many new ML roles"}


def test_skeptic_rejects_mere_disagreement():
    with pytest.raises(ValidationError):
        SkepticOut.model_validate({"alternatives": [
            {"alternative": "The hypothesis is wrong and not supported by anything", "discriminating_test": TEST},
            {"alternative": "Replacement hiring after attrition, not a new AI team", "discriminating_test": TEST}]})


def test_skeptic_needs_two_alternatives_and_a_real_tool():
    ok = {"alternative": "Replacement hiring after attrition, not a new AI team", "discriminating_test": TEST}
    with pytest.raises(ValidationError):
        SkepticOut.model_validate({"alternatives": [ok]})
    with pytest.raises(ValidationError):
        SkepticOut.model_validate({"alternatives": [ok, {**ok, "discriminating_test": {**TEST, "tool": "web_search"}}]})
    assert len(SkepticOut.model_validate({"alternatives": [ok, ok]}).alternatives) == 2


def test_finding_must_cite_something():
    with pytest.raises(ValidationError):
        Finding(summary="it seems true", stance="supports", relevance=0.5)
    assert Finding(url="https://x.com/a", summary="role exists", stance="supports", relevance=0.5)


def test_prediction_signal_types_are_checked():
    with pytest.raises(ValidationError):
        TestablePrediction(claim="Acme launches an AI thing", horizon_days=30, signal_types=["rumour"], keywords=["AI"])


# ---------------- judge + DB (uses the temp DB from conftest) ----------------
@pytest.fixture()
def db():
    from app.db.models import Base, Competitor
    from app.db.session import SessionLocal, engine

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    s = SessionLocal()
    s.add(Competitor(id=1, name="Acme", domain="acme.com", product_urls=[]))
    s.commit()
    yield s
    s.close()


def _sig(db, i, group, summary="Acme launches AI agents", cat="product", conf=0.95, age=1):
    from app.db.models import Signal

    s = Signal(id=i, competitor_id=1, type="feature_launch", category=cat, summary=summary, evidence_url=f"https://acme.com/{i}",
               observed_at=NOW - timedelta(days=age), origin_group=group, event_confidence=conf, raw={"kind": "blog"})
    db.add(s)
    db.flush()
    return s


def _hyp(db):
    from app.db.models import Hypothesis

    h = Hypothesis(competitor_id=1, statement="Acme is pivoting to AI agents", category="product", confidence=0.2, prior=0.2,
                   testable_predictions=[{"claim": "Acme ships an agent SDK", "horizon_days": 60,
                                          "signal_types": ["feature_launch"], "keywords": ["SDK"]}])
    db.add(h)
    db.flush()
    return h


def test_judge_independence_and_history(db):
    from app.agents import judge
    from app.db.models import BeliefHistory

    h = _hyp(db)
    a, b, c = _sig(db, 1, "press"), _sig(db, 2, "press"), _sig(db, 3, "other")
    for s in (a, b):
        judge.link_evidence(db, h, s, "supports", 0.8, "same announcement", "strategist", "acme.com")
    judge.rescore(db, h, NOW, "two copies of one announcement")
    two_same = h.confidence
    judge.link_evidence(db, h, c, "supports", 0.8, "independent", "strategist", "acme.com")
    judge.rescore(db, h, NOW, "independent evidence")
    assert h.confidence > two_same > 0.2
    assert db.query(BeliefHistory).filter_by(hypothesis_id=h.id).count() == 2
    assert judge.link_evidence(db, h, c, "supports", 0.8, "dup", "strategist") is None  # no double counting


def test_strategist_same_event_merge(db):
    from app.agents.strategist import merge_same_event

    a, b = _sig(db, 1, "news:a", age=2), _sig(db, 2, "news:b", age=1)
    assert merge_same_event(db, {1: a, 2: b}, [[1, 2], [2, 99]]) == 1
    assert b.origin_group == "news:a" and b.raw["origin_group_before_merge"] == "news:b"


def test_direct_observations_are_never_merged(db):
    """Regression (synthetic injection test): the strategist merged a pricing-page diff, a docs diff and a CFO
    quote into one origin group, erasing their independence."""
    from app.agents.strategist import merge_same_event

    p1, p2 = _sig(db, 1, "page:1"), _sig(db, 2, "page:2")
    p1.raw, p2.raw = {"kind": "page"}, {}
    n = _sig(db, 3, "news:3")
    n.raw = {"kind": "news"}
    assert merge_same_event(db, {1: p1, 2: p2, 3: n}, [[1, 2, 3]]) == 0
    assert (p1.origin_group, p2.origin_group, n.origin_group) == ("page:1", "page:2", "news:3")


def test_predictions_register_and_resolve(db):
    from app.agents import judge

    h = _hyp(db)
    h.confidence = 0.65
    preds = judge.register_predictions(db, h, NOW - timedelta(days=10))
    assert len(preds) == 1 and judge.register_predictions(db, h, NOW) == []  # only once
    _sig(db, 5, "g5", summary="Acme ships Agent SDK 1.0", age=3)
    assert judge.resolve_predictions(db, NOW) == 1 and preds[0].outcome == "hit" and preds[0].evidence_id == 5


def test_alert_requires_skeptic(db):
    from app.agents import judge
    from app.db.models import Competitor, SkepticChallenge

    h = _hyp(db)
    h.status, h.confidence = "likely", 0.75
    comp = db.get(Competitor, 1)
    assert judge.alert_policy(db, comp, h, "plausible", NOW) is None  # unchallenged -> no alert
    db.add(SkepticChallenge(hypothesis_id=h.id, alternative="A routine rebrand of existing ML features",
                            discriminating_test="x", verdict="alternative_refuted"))
    db.flush()
    a = judge.alert_policy(db, comp, h, "plausible", NOW)
    assert a is not None and "uncalibrated" in a.body
    assert judge.alert_policy(db, comp, h, "likely", NOW) is None  # no repeat while it stays likely


def test_refound_url_does_not_count_as_new_evidence(db):
    """Regression (real Airtable run): the investigator re-found postings already summarised by a hiring
    signal and they were counted as independent evidence (0.57 -> 0.88)."""
    from app.agents.investigator import known_signal_for_url
    from app.db.models import Signal

    db.add(Signal(id=9, competitor_id=1, type="hiring_tech_keyword", category="hiring", summary="2 postings mention AI",
                  evidence_url="https://boards.example/jobs/1", observed_at=NOW, origin_group="jobs:1:W47",
                  raw={"postings": [{"url": "https://boards.example/jobs/1"}, {"url": "https://boards.example/jobs/2"}]}))
    db.flush()
    exact, group = known_signal_for_url(db, 1, "https://boards.example/jobs/1")
    assert exact is not None and exact.id == 9
    exact, group = known_signal_for_url(db, 1, "https://boards.example/jobs/2")
    assert exact is None and group == "jobs:1:W47"
    assert known_signal_for_url(db, 1, "https://elsewhere.example/x") == (None, None)


def test_likely_requires_a_skeptic_challenge(db):
    from app.agents import judge
    from app.db.models import SkepticChallenge

    h = _hyp(db)
    for i in range(1, 5):
        judge.link_evidence(db, h, _sig(db, i, f"g{i}"), "supports", 0.9, "strong", "strategist", "acme.com")
    judge.rescore(db, h, NOW, "lots of evidence")
    assert h.confidence >= 0.7 and h.status == "plausible"  # gated
    db.add(SkepticChallenge(hypothesis_id=h.id, alternative="Seasonal launch campaign, not a strategic shift",
                            discriminating_test="x", verdict="inconclusive"))
    db.flush()
    judge.rescore(db, h, NOW, "after skeptic")
    assert h.status == "likely"


def test_lenient_contracts_still_guard_evidence():
    from app.agents.schemas import InvestigatorStep

    assert InvestigatorStep.model_validate({"observation": "done"}).action == "stop"
    step = InvestigatorStep.model_validate({"findings": [{"summary": "no relevant results", "stance": "neutral",
                                                          "relevance": 0, "url": ""},
                                                         {"summary": "role exists", "stance": "supports",
                                                          "relevance": 0.5, "url": "https://x.example/a"}]})
    assert [f.url for f in step.findings] == ["https://x.example/a"]
    p = TestablePrediction(claim="Acme launches an AI thing", horizon_days=30, signal_types=["rumour", "feature_launch"], keywords=["AI"])
    assert p.signal_types == ["feature_launch"]
    with pytest.raises(ValidationError):  # citations are still mandatory
        Finding(summary="it seems true", stance="supports", relevance=0.5)
