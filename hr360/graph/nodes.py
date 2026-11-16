"""Graph node wrappers: tracing, retry/fallback, report node and the human-approval node."""
from __future__ import annotations

import json
import logging
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Callable

from langgraph.types import interrupt
from sqlalchemy import insert

from hr360.agents.base import AgentContext
from hr360 import app_settings
from hr360.data.schema import outbox
from hr360.email_sender import send_email
from hr360.reporting.report import generate_report
from hr360.security.rbac import role_can

log = logging.getLogger("hr360.graph")


def guarded(name: str, fn: Callable[[dict], dict], ctx: AgentContext) -> Callable[[dict], dict]:
    """Wrap an agent function: timing + audit log + retry + safe fallback (never raises)."""
    attempts = 1 + ctx.settings.node_retries

    def node(state: dict) -> dict:
        t0 = time.perf_counter()
        last: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                out = fn(state) or {}
                ms = round((time.perf_counter() - t0) * 1000)
                status = {name: {"status": "completed", "duration_ms": ms, "attempts": attempt}}
                out["agent_execution_status"] = {**out.get("agent_execution_status", {}), **status}
                ctx.audit_log.record("agent_run", request_id=state.get("request_id"), actor=state.get("user_id"),
                                     role=state.get("user_role"), agent=name,
                                     detail={"status": "completed", "duration_ms": ms, "attempts": attempt})
                log.info("[%s] %s completed in %d ms", state.get("request_id"), name, ms)
                return out
            except Exception as exc:  # noqa: BLE001 - deliberate: isolate agent failures
                last = exc
                log.warning("[%s] %s attempt %d/%d failed: %s", state.get("request_id"), name, attempt, attempts, exc)
        ms = round((time.perf_counter() - t0) * 1000)
        ctx.audit_log.record("agent_run", request_id=state.get("request_id"), actor=state.get("user_id"),
                             role=state.get("user_role"), agent=name,
                             detail={"status": "failed", "error": str(last)[:300]})
        return {"errors": [f"{name}: {type(last).__name__}: {last}"],
                "agent_execution_status": {name: {"status": "failed", "duration_ms": ms, "attempts": attempts}}}

    node.__name__ = f"{name}_node"
    return node


def make_report_node(ctx: AgentContext) -> Callable[[dict], dict]:
    def report(state: dict) -> dict:
        paths = generate_report(state["request_id"], state.get("task_type", ""), state,
                                ctx.settings.reports_dir, ctx.settings.as_of)
        return {"report_paths": paths}
    return report


def make_approval_node(ctx: AgentContext) -> Callable[[dict], dict]:
    """Human-in-the-loop gate. Pauses the graph (checkpointed) until an authorised human decides.
    Nothing before ``interrupt`` may have side effects: the node is re-run from the top on resume."""

    def approval(state: dict) -> dict:
        drafts = state.get("generated_email_drafts") or []
        if not drafts:
            return {"approval_status": "not_required",
                    "agent_execution_status": {"approval": {"status": "completed", "detail": "nothing to approve"}}}

        decision = interrupt({
            "type": "approval_request", "request_id": state.get("request_id"),
            "message": "Review the prepared email drafts. Nothing is sent until an authorised approver approves.",
            "drafts": drafts, "requested_by": state.get("user_id")})

        approver, role = decision.get("approver_id", "unknown"), decision.get("approver_role", "employee")
        rid = state.get("request_id")
        if not role_can(role, "approve_actions"):
            ctx.audit_log.record("approval_denied_unauthorized", request_id=rid, actor=approver, role=role, agent="approval",
                                 detail="approver lacks approve_actions permission")
            return {"approval_status": "rejected_unauthorized", "approval_decision": decision,
                    "errors": [f"approval: role '{role}' may not approve actions"],
                    "agent_execution_status": {"approval": {"status": "completed", "detail": "unauthorised approver"}}}

        if not decision.get("approved"):
            updated = [{**d, "status": "rejected"} for d in drafts]
            ctx.audit_log.record("approval_rejected", request_id=rid, actor=approver, role=role, agent="approval",
                                 detail={"comment": decision.get("comment", "")})
            return {"approval_status": "rejected", "approval_decision": decision, "generated_email_drafts": updated,
                    "agent_execution_status": {"approval": {"status": "completed", "detail": "rejected"}}}

        chosen = set(decision.get("approved_draft_ids") or [d["draft_id"] for d in drafts])
        updated, queued = [], 0
        for d in drafts:
            if d["draft_id"] in chosen:
                updated.append({**d, "status": _queue_email(ctx, d, approver, rid)})
                queued += 1
            else:
                updated.append({**d, "status": "rejected"})
        ctx.audit_log.record("approval_granted", request_id=rid, actor=approver, role=role, agent="approval",
                             detail={"queued": queued, "comment": decision.get("comment", "")})
        return {"approval_status": "approved", "approval_decision": decision, "generated_email_drafts": updated,
                "agent_execution_status": {"approval": {"status": "completed", "detail": ", ".join(
                    f"{k}={v}" for k, v in Counter(u["status"] for u in updated).items())}}}

    return approval


def _queue_email(ctx: AgentContext, draft: dict, approver: str, request_id: str | None) -> str:
    """Release an APPROVED draft: record it in the outbox table and send via Resend if configured
    (see hr360/email_sender.py for the safety rules). Returns the resulting draft status."""
    first, email = ctx.db.employee_contact(draft["employee_id"])
    body = draft["body"].replace("{first_name}", first or "there")
    cfg = app_settings.get_all(ctx.audit_log.engine)
    result = send_email(email, draft["subject"], body, draft["employee_id"], f"{request_id}-{draft['draft_id']}",
                        mode=None if cfg.get("email_mode") in (None, "env") else cfg["email_mode"],
                        redirect_to=cfg.get("email_redirect_to"))
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "request_id": request_id,
              "draft_id": draft["draft_id"], "employee_id": draft["employee_id"], "to_addr": result.to or email,
              "subject": draft["subject"], "body": body, "approved_by": approver,
              "delivery": f"{result.delivery}" + (f" ({result.detail})" if result.detail else ""),
              "provider_id": result.provider_id}
    with ctx.audit_log.engine.begin() as c:
        c.execute(insert(outbox).values(**record))
    try:  # local convenience copy; unavailable on read-only hosts
        ctx.settings.outbox_path.parent.mkdir(parents=True, exist_ok=True)
        with open(ctx.settings.outbox_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass
    return {"sent": "sent", "failed": "failed"}.get(result.delivery, "queued")
