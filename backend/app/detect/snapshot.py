from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import RawObservation
from app.db.models import Snapshot


def last_snapshot(db: Session, source_id: int, as_of: datetime | None = None) -> Snapshot | None:
    q = select(Snapshot).where(Snapshot.source_id == source_id)
    if as_of is not None:
        q = q.where(Snapshot.observed_at <= as_of)
    return db.scalars(q.order_by(Snapshot.observed_at.desc(), Snapshot.id.desc()).limit(1)).first()


def store(db: Session, obs: RawObservation, prev: Snapshot | None) -> tuple[Snapshot, bool]:
    """Store a snapshot only when content changed. Returns (current snapshot, changed?)."""
    if prev is not None and prev.content_hash == obs.content_hash:
        return prev, False
    snap = Snapshot(source_id=obs.source_id, fetched_at=obs.fetched_at, observed_at=obs.observed_at,
                    content_hash=obs.content_hash, content_text=obs.content_text, meta=obs.meta)
    db.add(snap)
    db.flush()
    return snap, True
