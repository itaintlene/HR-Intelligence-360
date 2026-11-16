"""High-level runner used by the UI and tests: start requests, pause at approval, resume."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from langgraph.types import Command
from sqlalchemy import insert, select, update

from hr360.agents.base import AgentContext
from hr360.graph.builder import build_graph, make_checkpointer
from hr360.data.engine import make_engine
from hr360.data.schema import OPS_METADATA, requests as requests_t
from hr360.security.audit_log import setup_logging


class HRRunner:
    def __init__(self, ctx: AgentContext | None = None, checkpointer=None):
        self.ctx = ctx or AgentContext.build()
        s = self.ctx.settings
        setup_logging(s.log_dir)
        self.graph = build_graph(self.ctx, checkpointer or make_checkpointer(s.checkpoint_path, s.database_url))
        self._engine = make_engine(s.ops_target)
        OPS_METADATA.create_all(self._engine)

    # ---- request registry ----
    def _upsert(self, rid: str, **kw) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._engine.begin() as c:
            exists = c.execute(select(requests_t.c.request_id).where(requests_t.c.request_id == rid)).first()
            if exists:
                c.execute(update(requests_t).where(requests_t.c.request_id == rid).values(**kw, updated_at=now))
            else:
                c.execute(insert(requests_t).values(
                    request_id=rid, user_id=kw.get("user_id"), role=kw.get("role"), query=kw.get("query"),
                    task_type=kw.get("task_type"), status=kw.get("status"), created_at=now, updated_at=now))

    def list_requests(self, status: str | None = None, limit: int = 50, user_id: str | None = None) -> list[dict]:
        q = select(requests_t).order_by(requests_t.c.created_at.desc()).limit(limit)
        if status is not None:
            q = q.where(requests_t.c.status == status)
        if user_id is not None:
            q = q.where(requests_t.c.user_id == user_id)
        with self._engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(q)]

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
