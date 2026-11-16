"""Append-only audit log (SQLite or Postgres) of agent execution and consequential actions,
plus standard Python logging setup."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import insert, select

from hr360.data.engine import make_engine
from hr360.data.schema import OPS_METADATA, audit_log


def setup_logging(log_dir: Path, level: int = logging.INFO) -> None:
    root = logging.getLogger("hr360")
    if root.handlers:
        return
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s :: %(message)s")
    try:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.FileHandler(log_dir / "hr360.log", encoding="utf-8")
    except OSError:  # read-only filesystem (serverless): log to stderr instead
        handler = logging.StreamHandler()
    handler.setFormatter(fmt)
    root.addHandler(handler)


class AuditLog:
    def __init__(self, target):
        self.engine = make_engine(target)
        OPS_METADATA.create_all(self.engine)

    def record(self, action: str, *, request_id: str | None = None, actor: str | None = None,
               role: str | None = None, agent: str | None = None, detail: dict | str | None = None) -> None:
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail, default=str)
        with self.engine.begin() as c:
            c.execute(insert(audit_log).values(
                ts=datetime.now(timezone.utc).isoformat(timespec="seconds"), request_id=request_id, actor=actor,
                role=role, agent=agent, action=action, detail=detail))

    def fetch(self, request_id: str | None = None, limit: int = 500) -> list[dict]:
        q = select(audit_log).order_by(audit_log.c.id.desc()).limit(limit)
        if request_id:
            q = q.where(audit_log.c.request_id == request_id)
        with self.engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(q)]
