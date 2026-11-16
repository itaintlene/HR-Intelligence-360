"""Append-only audit log (SQLite) of agent execution and consequential actions,
plus standard Python logging setup."""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

_DDL = """CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, request_id TEXT,
    actor TEXT, role TEXT, agent TEXT, action TEXT NOT NULL, detail TEXT)"""


def setup_logging(log_dir: Path, level: int = logging.INFO) -> None:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("hr360")
    if root.handlers:
        return
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s :: %(message)s")
    fh = logging.FileHandler(log_dir / "hr360.log", encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)


class AuditLog:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as c, c:
            c.execute(_DDL)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def record(self, action: str, *, request_id: str | None = None, actor: str | None = None,
               role: str | None = None, agent: str | None = None, detail: dict | str | None = None) -> None:
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail, default=str)
        with closing(self._conn()) as c, c:
            c.execute(
                "INSERT INTO audit_log (ts, request_id, actor, role, agent, action, detail) VALUES (?,?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), request_id, actor, role, agent, action, detail),
            )

    def fetch(self, request_id: str | None = None, limit: int = 500) -> list[dict]:
        q, args = "SELECT * FROM audit_log", ()
        if request_id:
            q, args = q + " WHERE request_id=?", (request_id,)
        q += " ORDER BY id DESC LIMIT ?"
        with closing(self._conn()) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute(q, (*args, limit))]
