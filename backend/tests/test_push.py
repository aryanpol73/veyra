"""Web Push: VAPID keys, subscriptions, delivery, cleanup of dead subscriptions, alert hook."""
import base64
from types import SimpleNamespace

import pytest

from app import push


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from app.db.models import Base, Competitor
    from app.db.session import SessionLocal, engine

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(push, "DATA_DIR", tmp_path)
    monkeypatch.setattr(push, "_keys", None)
    s = SessionLocal()
    s.add(Competitor(id=1, name="Acme", domain="acme.example", product_urls=[]))
    s.commit()
    yield s
    s.close()


@pytest.fixture()
def sent(monkeypatch):
    """Capture webpush calls; endpoints containing 'gone' answer 410, 'flaky' answer 500."""
    import pywebpush

    calls = []

    def fake_webpush(subscription_info, data, **kw):
        ep = subscription_info["endpoint"]
        calls.append((ep, data, kw))
        if "gone" in ep or "flaky" in ep:
            raise pywebpush.WebPushException("push failed", response=SimpleNamespace(status_code=410 if "gone" in ep else 500))
    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)
    return calls


def test_vapid_keys_are_generated_once_and_persisted(db, tmp_path):
    priv, pub = push.vapid_keys()
    raw = base64.urlsafe_b64decode(pub + "=" * (-len(pub) % 4))
    assert len(raw) == 65 and raw[0] == 4  # uncompressed P-256 point, what browsers expect
    assert (tmp_path / "vapid.json").exists()
    push._keys = None
    assert push.vapid_keys() == (priv, pub)  # reloaded from disk, not regenerated


def test_subscribe_is_idempotent_and_unsubscribe_removes(db):
    from app.db.models import PushSubscription

    push.subscribe(db, "https://push.example/a", "p" * 20, "a" * 10, "UA")
    push.subscribe(db, "https://push.example/a", "q" * 20, "b" * 10, "UA")  # same device re-subscribing
    assert db.query(PushSubscription).count() == 1 and db.query(PushSubscription).one().p256dh == "q" * 20
    assert push.unsubscribe(db, "https://push.example/a") and db.query(PushSubscription).count() == 0


def test_send_removes_dead_subscriptions(db, sent):
    from app.db.models import PushSubscription

    for ep in ("https://push.example/ok", "https://push.example/gone", "https://push.example/flaky"):
        push.subscribe(db, ep, "p" * 20, "a" * 10, None)
    r = push.send_to_all(db, {"title": "t", "body": "b", "url": "/"})
    assert r == {"sent": 1, "failed": 1, "removed": 1}
    left = {s.endpoint: s.failures for s in db.query(PushSubscription)}
    assert left == {"https://push.example/ok": 0, "https://push.example/flaky": 1}
    assert all(kw["vapid_claims"]["sub"].startswith("mailto:") for _, _, kw in sent)


def test_new_alerts_are_pushed_once_and_marked_delivered(db, sent):
    from app.db.models import Alert

    push.subscribe(db, "https://push.example/ok", "p" * 20, "a" * 10, None)
    db.add(Alert(id=7, competitor_id=1, priority="critical", title="Acme: raises prices 30%", body="Prices up\nEvidence: x"))
    db.flush()
    r = push.notify_alerts(db, [7])
    assert r["sent"] == 1 and db.get(Alert, 7).delivered_at is not None and db.get(Alert, 7).channel == "push"
    import json

    payload = json.loads(sent[0][1])
    assert payload["title"].startswith("Critical") and payload["url"] == "/feed" and sent[0][2]["headers"]["Urgency"] == "high"
    push.notify_alerts(db, [7])
    assert len(sent) == 1  # already delivered: not sent twice


def test_push_routes_validate_and_require_https(db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        assert len(c.get("/push/key").json()["public_key"]) > 80
        bad = {"endpoint": "http://insecure.example/x", "keys": {"p256dh": "p" * 20, "auth": "a" * 10}}
        assert c.post("/push/subscribe", json=bad).status_code == 422
        good = {"endpoint": "https://push.example/x", "keys": {"p256dh": "p" * 20, "auth": "a" * 10}}
        assert c.post("/push/subscribe", json=good).status_code == 201
        assert c.get("/push/status").json()["subscriptions"] == 1
