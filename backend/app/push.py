"""Web Push: alerts reach every subscribed phone/desktop even when Veyra isn't open.

How delivery works: the server encrypts each alert and hands it to the BROWSER VENDOR's push service
(Google FCM for Chrome/Android/Edge, Mozilla for Firefox, Apple for Safari/iOS). That service delivers it
to the device wherever it is. So the server needs outbound internet only; the device needs to have
subscribed once, from a secure origin (https:// or http://localhost).

VAPID keys identify this server to the push services. They are generated on first use and stored in
DATA_DIR/vapid.json (keep it: new keys invalidate every existing subscription), or set
VAPID_PRIVATE_KEY / VAPID_PUBLIC_KEY to supply your own.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import threading
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DATA_DIR, get_settings
from app.db.models import Alert, Competitor, PushSubscription

log = logging.getLogger("veyra.push")
_lock = threading.Lock()
_keys: tuple[str, str] | None = None  # (private key, base64url; public key, base64url uncompressed point)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def vapid_keys() -> tuple[str, str]:
    """(private, public) as base64url. Env vars win; else load or create DATA_DIR/vapid.json."""
    global _keys
    if _keys:
        return _keys
    with _lock:
        env_priv, env_pub = os.environ.get("VAPID_PRIVATE_KEY", ""), os.environ.get("VAPID_PUBLIC_KEY", "")
        if env_priv and env_pub:
            _keys = (env_priv, env_pub)
            return _keys
        path = DATA_DIR / "vapid.json"
        if path.exists():
            d = json.loads(path.read_text("utf-8"))
            _keys = (d["private_key"], d["public_key"])
            return _keys
        key = ec.generate_private_key(ec.SECP256R1())
        priv = _b64(key.private_numbers().private_value.to_bytes(32, "big"))
        pub = _b64(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"private_key": priv, "public_key": pub,
                                    "created_at": datetime.now(timezone.utc).isoformat()}), "utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        log.info("generated VAPID keys in %s", path)
        _keys = (priv, pub)
        return _keys


def _subject() -> str:
    return f"mailto:{get_settings().user_agent_email}"


def subscribe(db: Session, endpoint: str, p256dh: str, auth: str, user_agent: str | None) -> PushSubscription:
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if sub is None:
        sub = PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth, user_agent=(user_agent or "")[:300])
        db.add(sub)
    else:  # keys rotate when a browser re-subscribes
        sub.p256dh, sub.auth, sub.failures = p256dh, auth, 0
    db.flush()
    return sub


def unsubscribe(db: Session, endpoint: str) -> bool:
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if sub:
        db.delete(sub)
        db.flush()
    return sub is not None


def send_to_all(db: Session, payload: dict, *, urgency: str = "normal", ttl: int = 24 * 3600) -> dict:
    """Deliver one notification to every subscription. Gone subscriptions (404/410) are deleted."""
    from pywebpush import WebPushException, webpush

    priv, _ = vapid_keys()
    sent = failed = removed = 0
    data = json.dumps(payload)
    for sub in db.scalars(select(PushSubscription)).all():
        try:
            webpush(subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                    data=data, vapid_private_key=priv, vapid_claims={"sub": _subject()},
                    ttl=ttl, headers={"Urgency": urgency}, timeout=15)
            sub.last_success_at, sub.failures = datetime.now(timezone.utc), 0
            sent += 1
        except WebPushException as e:
            code = getattr(e.response, "status_code", None)
            if code in (404, 410):  # the browser dropped this subscription (uninstalled, revoked, expired)
                db.delete(sub)
                removed += 1
            else:
                sub.failures += 1
                failed += 1
                log.warning("push to %s failed (%s): %s", sub.endpoint[:60], code, str(e)[:200])
        except Exception as e:  # noqa: BLE001 - network etc.; never break the caller (a cycle)
            sub.failures += 1
            failed += 1
            log.warning("push to %s failed: %s", sub.endpoint[:60], e)
    db.flush()
    return {"sent": sent, "failed": failed, "removed": removed}


def alert_payload(db: Session, a: Alert) -> dict:
    comp = db.get(Competitor, a.competitor_id)
    body = (a.body or "").split("\n")
    url = f"/hypotheses?id={a.hypothesis_id}" if a.hypothesis_id else "/feed"
    return {"title": f"{'Critical' if a.priority == 'critical' else 'Veyra alert'}: {comp.name if comp else ''}".strip(),
            "body": (a.title.split(": ", 1)[-1] + ("\n" + body[0] if body and body[0] else ""))[:240],
            "url": url, "tag": f"veyra-alert-{a.id}", "priority": a.priority}


def notify_alerts(db: Session, alert_ids: list[int]) -> dict:
    """Push each new alert (called after a cycle commits). Marks alerts delivered."""
    totals = {"sent": 0, "failed": 0, "removed": 0, "alerts": 0}
    if not alert_ids or not db.scalar(select(PushSubscription.id).limit(1)):
        return totals
    for a in db.scalars(select(Alert).where(Alert.id.in_(alert_ids), Alert.delivered_at.is_(None))).all():
        r = send_to_all(db, alert_payload(db, a), urgency="high" if a.priority == "critical" else "normal")
        for k in ("sent", "failed", "removed"):
            totals[k] += r[k]
        totals["alerts"] += 1
        if r["sent"]:
            a.delivered_at, a.channel = datetime.now(timezone.utc), "push"
    db.flush()
    return totals
