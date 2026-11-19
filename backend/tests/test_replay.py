"""Leakage tests: in replay, nothing observed after as_of may reach detectors, tools or the agents."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.collectors.base import sha

JAN, FEB, MAR, APR = (datetime(2026, m, 15, tzinfo=timezone.utc) for m in (1, 2, 3, 4))
URL = "https://acme.example/pricing"


@pytest.fixture()
def db():
    from app.db.models import Base, Competitor, Source
    from app.db.session import SessionLocal, engine

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    s = SessionLocal()
    c = Competitor(id=1, name="Acme", domain="acme.example", pricing_url=URL, product_urls=[])
    c.sources = [Source(id=1, source_type="page", url=URL, active=True)]
    s.add(c)
    s.commit()
    yield s
    s.close()


@pytest.fixture()
def store(tmp_path):
    from app.eval.dataset import slug, source_key
    from app.eval.replay import ReplayStore

    folder = tmp_path / slug("Acme") / source_key(URL)
    folder.mkdir(parents=True)
    for when, text in [(JAN, "Pro plan\n$20 per user/month"), (MAR, "Pro plan\n$25 per user/month")]:
        ts = when.strftime("%Y%m%d%H%M%S")
        (folder / f"{ts}.json").write_text(json.dumps({
            "url": URL, "source_type": "page", "wayback_ts": ts, "wayback_url": f"https://web.archive.org/web/{ts}/{URL}",
            "observed_at": when.isoformat(), "content_text": text, "content_hash": sha(text), "meta": {}}))
    return ReplayStore(tmp_path)


def test_store_never_yields_future_captures(store):
    assert [c.observed_at for c in store.between("Acme", URL, None, FEB)] == [JAN]
    assert [c.observed_at for c in store.between("Acme", URL, JAN, APR)] == [MAR]
    assert store.between("Acme", URL, None, JAN - timedelta(days=1)) == []


def test_ingest_step_only_sees_the_past(db, store):
    from app.db.models import Signal, Snapshot
    from app.eval.replay import ingest_step

    ingest_step(db, FEB, store)
    assert db.query(Signal).count() == 0  # Jan capture is only the baseline; Mar is in the future
    assert all(s.observed_at.replace(tzinfo=timezone.utc) <= FEB for s in db.query(Snapshot).all())
    new = ingest_step(db, APR, store)
    sig = db.query(Signal).one()
    assert new == {1: [sig.id]} and sig.type == "price_change" and sig.replay
    assert sig.observed_at.replace(tzinfo=timezone.utc) == MAR and sig.detected_at.replace(tzinfo=timezone.utc) == APR
    assert "web.archive.org" in sig.evidence_url  # evidence is the archived capture


def test_tools_respect_as_of(db, store):
    from app.agents.tools import ToolContext, fetch_url, query_signals, web_search
    from app.db.models import Competitor
    from app.eval.replay import ingest_step

    ingest_step(db, APR, store)
    comp = db.get(Competitor, 1)
    assert "no matching signals" in query_signals(ToolContext(db=db, competitor=comp, as_of=FEB)).text
    assert "S" in query_signals(ToolContext(db=db, competitor=comp, as_of=APR)).text
    assert "disabled" in fetch_url(ToolContext(db=db, competitor=comp, as_of=APR), url=URL).text
    assert "not available" in web_search(ToolContext(db=db, competitor=comp, as_of=APR)).text


def test_no_network_in_replay():
    from app.eval.replay import NoNetworkFetcher

    with pytest.raises(AssertionError, match="LEAKAGE GUARD"):
        NoNetworkFetcher().get("https://example.com")


def test_monthly_steps():
    from app.eval.replay import monthly_steps

    steps = monthly_steps(datetime(2026, 5, 1, tzinfo=timezone.utc), datetime(2026, 7, 18, tzinfo=timezone.utc))
    assert [d.strftime("%m-%d") for d in steps] == ["05-01", "06-01", "07-01", "07-18"]


def test_wilson_interval():
    from app.eval.metrics import wilson

    lo, hi = wilson(3, 4)
    assert 0.3 < lo < 0.75 < hi <= 1.0
    assert wilson(0, 0) is None
    lo, hi = wilson(0, 5)
    assert lo == 0.0 and hi < 0.5


def test_metrics_lead_time_precision_recall(db):
    from datetime import date

    from app.db.models import BeliefHistory, Hypothesis
    from app.eval.metrics import GTEvent, evaluate

    h1 = Hypothesis(id=1, competitor_id=1, statement="Acme is moving to usage-based billing", category="pricing",
                    confidence=0.72, prior=0.2)
    h2 = Hypothesis(id=2, competitor_id=1, statement="Acme is opening an office in Tokyo", category="hiring",
                    confidence=0.55, prior=0.2)
    db.add_all([h1, h2])
    db.flush()
    db.add_all([BeliefHistory(hypothesis_id=1, ts=FEB, confidence=0.3, delta=0, reason="x"),
                BeliefHistory(hypothesis_id=1, ts=MAR, confidence=0.6, delta=0.3, reason="x"),
                BeliefHistory(hypothesis_id=2, ts=MAR, confidence=0.55, delta=0.35, reason="x")])
    db.commit()
    events = [GTEvent("e1", "Acme", "Usage-based billing launched", "pricing", date(2026, 3, 25), "u", ["usage-based"]),
              GTEvent("e2", "Acme", "Acquires Widget", "market", date(2026, 3, 30), "u", ["acquir"]),
              GTEvent("e3", "Acme", "Out of window", "market", date(2027, 1, 1), "u", ["x"])]
    m = evaluate(db, events, (JAN, APR))
    assert m.n_events == 2 and m.true_positives == 1 and m.recall == 0.5
    assert m.events[0].lead_days == 10.0 and m.early_detections == 1  # detected Mar 15, announced Mar 25
    assert m.n_detected == 2 and m.precision == 0.5 and m.fp_rate == 0.5
    high = next(b for b in m.calibration if b["bin"] == "high")
    assert high["n"] == 1 and high["hits"] == 1


def test_metrics_ignore_synthetic_data(db):
    from app.db.models import BeliefHistory, Competitor, Hypothesis
    from app.eval.metrics import evaluate

    db.add(Competitor(id=9, name="SynthCo-x", domain="s.example", product_urls=[], notes="SYNTHETIC test competitor"))
    db.flush()
    db.add_all([Hypothesis(id=1, competitor_id=1, statement="real", category="market", confidence=0.6, prior=0.2),
                Hypothesis(id=2, competitor_id=9, statement="fake", category="market", confidence=0.6, prior=0.2, synthetic=True)])
    db.flush()
    db.add_all([BeliefHistory(hypothesis_id=i, ts=MAR, confidence=0.6, delta=0.4, reason="x") for i in (1, 2)])
    db.commit()
    m = evaluate(db, [], (JAN, APR))
    assert m.n_hypotheses == 1 and m.n_detected == 1
