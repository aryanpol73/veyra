"""The belief engine is the key correctness piece: these tests pin its behaviour."""
from datetime import datetime, timedelta, timezone

import pytest

from app.belief import engine as be

NOW = datetime(2026, 11, 18, tzinfo=timezone.utc)


def ev(i, stance="supports", group=None, cat="product", rel=1.0, relevance=0.8, conf=0.95, age=0):
    return be.EvidenceItem(id=i, stance=stance, relevance=relevance, reliability=rel, event_confidence=conf,
                           observed_at=NOW - timedelta(days=age), origin_group=group or f"g{i}", category=cat)


def test_no_evidence_returns_prior():
    assert be.score(0.2, [], NOW).confidence == pytest.approx(0.2)


def test_support_raises_contradiction_lowers():
    up = be.score(0.2, [ev(1)], NOW).confidence
    down = be.score(0.2, [ev(1, "contradicts")], NOW).confidence
    assert up > 0.2 > down


def test_neutral_does_nothing():
    assert be.score(0.2, [ev(1, "neutral")], NOW).confidence == pytest.approx(0.2)


def test_same_origin_group_counts_once_plus_small_extra():
    one = be.score(0.2, [ev(1)], NOW).logit - be.logit(0.2)
    same = be.score(0.2, [ev(1, group="press"), ev(2, group="press"), ev(3, group="press")], NOW)
    indep = be.score(0.2, [ev(1), ev(2), ev(3)], NOW)
    gained_same = same.logit - be.logit(0.2)
    assert gained_same == pytest.approx(one * (1 + 2 * be.SAME_GROUP_WEIGHT))
    assert indep.confidence > same.confidence
    assert sorted(same.independence.values()) == [0.2, 0.2, 1.0]


def test_strongest_item_in_group_gets_full_weight():
    r = be.score(0.2, [ev(1, group="g", rel=0.4), ev(2, group="g", rel=1.0)], NOW)
    assert r.independence[2] == 1.0 and r.independence[1] == 0.2


def test_recency_decay_halves_at_half_life():
    assert be.recency_decay(NOW - timedelta(days=45), NOW, "hiring") == pytest.approx(0.5)
    assert be.recency_decay(NOW - timedelta(days=21), NOW, "early_signal") == pytest.approx(0.5)
    fresh = be.score(0.2, [ev(1, cat="hiring")], NOW).confidence
    old = be.score(0.2, [ev(1, cat="hiring", age=90)], NOW).confidence
    assert fresh > old > 0.2


def test_category_cap_prevents_runaway():
    many = [ev(i) for i in range(40)]
    r = be.score(0.2, many, NOW)
    assert "product" in r.capped_categories
    assert r.logit - be.logit(0.2) == pytest.approx(be.CATEGORY_CAP)
    assert r.confidence < 0.95


def test_low_reliability_counts_less():
    official = be.score(0.2, [ev(1, rel=1.0)], NOW).confidence
    ct = be.score(0.2, [ev(1, rel=0.35)], NOW).confidence
    assert official > ct > 0.2


def test_skeptic_surviving_alternative_lowers_refuted_raises():
    base = be.score(0.2, [ev(1), ev(2)], NOW).confidence
    assert be.score(0.2, [ev(1), ev(2)], NOW, ["alternative_supported"]).confidence < base
    assert be.score(0.2, [ev(1), ev(2)], NOW, ["alternative_refuted"]).confidence > base
    assert be.score(0.2, [ev(1), ev(2)], NOW, ["inconclusive"]).confidence == pytest.approx(base)


def test_status_thresholds_and_confirmed_needs_primary():
    kw = dict(max_confidence_seen=0.5, has_primary_support=False, has_contradiction=False)
    assert be.status_for(0.3, **{**kw, "max_confidence_seen": 0.3}) == "emerging"
    assert be.status_for(0.5, **kw) == "plausible"
    assert be.status_for(0.75, **kw) == "likely"
    assert be.status_for(0.95, **kw) == "likely"
    assert be.status_for(0.95, **{**kw, "has_primary_support": True}) == "confirmed"
    assert be.status_for(0.15, **kw) == "stale"
    assert be.status_for(0.05, **{**kw, "has_contradiction": True}) == "refuted"


def test_source_reliability_mapping():
    assert be.source_reliability("page", {}) == 1.0
    assert be.source_reliability("news", {"kind": "blog"}) == 1.0
    assert be.source_reliability("news", {"kind": "news"}, "https://techcrunch.com/x") == 0.7
    assert be.source_reliability("news", {"kind": "news"}, "https://randomblog.io/x") == 0.4
    assert be.source_reliability("early_signal", {}) == 0.35
    assert be.source_reliability(None, {}, "https://figma.com/blog/x", "figma.com") == 1.0


def test_deterministic():
    items = [ev(1), ev(2, "contradicts", group="x"), ev(3, group="x", cat="hiring", age=30)]
    assert be.score(0.2, items, NOW).confidence == be.score(0.2, items, NOW).confidence
