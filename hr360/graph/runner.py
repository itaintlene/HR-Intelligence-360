"""High-level runner used by the UI and tests: start requests, pause at approval, resume."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from langgraph.types import Command

from hr360.agents.base import AgentContext
from hr360.graph.builder import build_graph, make_checkpointer
from hr360.security.audit_log import setup_logging

_DDL = """CREATE TABLE IF NOT EXISTS requests (
    request_id TEXT PRIMARY KEY, user_id TEXT, role TEXT, query TEXT, task_type TEXT,
    status TEXT, created_at TEXT, updated_at TEXT)"""


class HRRunner:
    def __init__(self, ctx: AgentContext | None = None, checkpointer=None):
        self.ctx = ctx or AgentContext.build()
        setup_logging(self.ctx.settings.log_dir)
        self.graph = build_graph(self.ctx, checkpointer or make_checkpointer(self.ctx.settings.checkpoint_path))
        self._ops = Path(self.ctx.settings.ops_db_path)
        with closing(sqlite3.connect(self._ops)) as c, c:
            c.execute(_DDL)

    # ---- request registry ----
    def _upsert(self, rid: str, **kw) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with closing(sqlite3.connect(self._ops)) as c, c:
            if c.execute("SELECT 1 FROM requests WHERE request_id=?", (rid,)).fetchone():
                sets = ", ".join(f"{k}=?" for k in kw) + ", updated_at=?"
                c.execute(f"UPDATE requests SET {sets} WHERE request_id=?", (*kw.values(), now, rid))
            else:
                c.execute("INSERT INTO requests (request_id,user_id,role,query,task_type,status,created_at,updated_at) "
                          "VALUES (:request_id,:user_id,:role,:query,:task_type,:status,:t,:t)",
                          {"request_id": rid, "user_id": kw.get("user_id"), "role": kw.get("role"), "query": kw.get("query"),
                           "task_type": kw.get("task_type"), "status": kw.get("status"), "t": now})

    def list_requests(self, status: str | None = None, limit: int = 50) -> list[dict]:
        q, args = "SELECT * FROM requests", ()
        if status:
            q, args = q + " WHERE status=?", (status,)
        with closing(sqlite3.connect(self._ops)) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute(q + " ORDER BY created_at DESC LIMIT ?", (*args, limit))]

    # ---- execution ----
    @staticmethod
    def _cfg(rid: str) -> dict:
        return {"configurable": {"thread_id": rid}, "recursion_limit": 60}

    def _snapshot(self, rid: str) -> dict:
        snap = self.graph.get_state(self._cfg(rid))
        values = snap.values or {}
        interrupts = [i.value for t in snap.tasks for i in getattr(t, "interrupts", [])]
        if snap.next and interrupts:
            status = "awaiting_approval"
        elif snap.next:
            status = "running"
        else:
            status = (values.get("final_response") or {}).get("status", "completed")
        self._upsert(rid, status=status, task_type=values.get("task_type"))
        return {"request_id": rid, "status": status, "interrupt": interrupts[0] if interrupts else None,
                "final_response": values.get("final_response"), "state": values}

    def run(self, query: str, user_id: str = "demo.user", role: str = "employee", files: list[str] | None = None,
            request_id: str | None = None) -> dict:
        rid = request_id or f"REQ-{uuid.uuid4().hex[:8]}"
        self._upsert(rid, user_id=user_id, role=role, query=query[:500], task_type=None, status="running")
        self.ctx.audit_log.record("request_received", request_id=rid, actor=user_id, role=role, agent="supervisor",
                                  detail={"files": [Path(f).name for f in files or []]})
        init = {"request_id": rid, "user_query": query, "user_id": user_id, "user_role": role,
                "uploaded_files": [str(f) for f in files or []], "errors": [], "employee_ids": []}
        self.graph.invoke(init, self._cfg(rid))
        return self._snapshot(rid)

    def resume(self, request_id: str, approver_id: str, approver_role: str, approved: bool,
               comment: str = "", approved_draft_ids: list[str] | None = None) -> dict:
        decision = {"approved": approved, "approver_id": approver_id, "approver_role": approver_role,
                    "comment": comment, "approved_draft_ids": approved_draft_ids}
        self.graph.invoke(Command(resume=decision), self._cfg(request_id))
        return self._snapshot(request_id)

    def get(self, request_id: str) -> dict:
        return self._snapshot(request_id)
