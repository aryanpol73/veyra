from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import AgentRun, Base

_settings = get_settings()
engine = create_engine(
    _settings.db_url,
    connect_args={"check_same_thread": False} if _settings.db_url.startswith("sqlite") else {},
)

if _settings.db_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):  # noqa: ANN001
        dbapi_conn.isolation_level = None  # let SQLAlchemy emit BEGIN so SAVEPOINTs work (pysqlite quirk)
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=10000")
        cur.close()

    @event.listens_for(engine, "begin")
    def _sqlite_begin(conn):  # noqa: ANN001
        conn.exec_driver_sql("BEGIN")


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def log_agent_run(
    kind: str,
    started_at: datetime,
    input: dict[str, Any],
    output: dict[str, Any],
    *,
    tool_calls: list[Any] | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    error: str | None = None,
    model: str | None = None,
) -> int:
    """Audit trail for every agent/LLM call. Cost is 0 on free Groq/Ollama tiers; tokens still logged.

    Inside a cycle the row is written through the cycle's own session (see `audit_into`): SQLite can't
    let a second connection write while the cycle's transaction is open."""
    run = AgentRun(
        kind=kind, started_at=started_at, ended_at=datetime.now(timezone.utc),
        input=input, output=output, tool_calls=tool_calls or [], model=model,
        tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=0.0, error=error,
    )
    shared = _audit_session.get()
    if shared is not None:
        shared.add(run)
        shared.flush()
        return run.id
    with session_scope() as db:
        db.add(run)
        db.flush()
        return run.id


_audit_session: contextvars.ContextVar[Session | None] = contextvars.ContextVar("audit_session", default=None)


@contextmanager
def audit_into(db: Session) -> Iterator[None]:
    """Route log_agent_run() into `db` for the duration (used by the cycle runner)."""
    token = _audit_session.set(db)
    try:
        yield
    finally:
        _audit_session.reset(token)
