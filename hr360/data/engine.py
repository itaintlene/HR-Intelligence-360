"""SQLAlchemy engine factory: a filesystem path -> SQLite, a postgres URL -> Postgres (psycopg 3)."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool


def is_url(target) -> bool:
    return "://" in str(target)


def normalize_url(url: str) -> str:
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_engine(target) -> Engine:
    if isinstance(target, Engine):
        return target
    if is_url(target):
        # NullPool: safe for serverless (no connections held across invocations); Neon pools server-side.
        return create_engine(normalize_url(str(target)), poolclass=NullPool, pool_pre_ping=True)
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})
