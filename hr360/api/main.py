"""FastAPI backend for the web UI.   Run:  uvicorn hr360.api.main:app --reload --port 8000"""
from __future__ import annotations

import os
import re
import uuid
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from hr360.agents.base import AgentContext
from hr360.api.auth import Principal, get_principal, require_permission
from hr360.config import Settings
from hr360.data.db import HRDatabase, public_employee_view
from hr360.data.sample_docs import generate_sample_docs
from hr360.data.synthetic import build_database
from hr360.graph.runner import HRRunner
from hr360.security.rbac import PERMISSIONS, role_can

MAX_UPLOAD = 15 * 1024 * 1024
ALLOWED_EXT = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".txt"}
# state keys safe to return, by sensitivity
PUBLIC_KEYS = ["task_type", "policy_answer", "approval_status", "errors", "agent_execution_status"]
STAFF_KEYS = ["audit_findings", "audit_summary", "workflow_recommendations", "generated_email_drafts", "workflow_summary",
              "document_metadata", "extracted_employee_data", "report_paths", "employee_ids"]
PM_KEYS = ["workflow_recommendations", "workflow_summary"]


_runner_lock = threading.Lock()


def get_runner() -> HRRunner:
    """Lazily build the runner on first use (works on serverless hosts that skip ASGI lifespan events)."""
    if getattr(app.state, "runner", None) is None:
        with _runner_lock:
            if getattr(app.state, "runner", None) is None:
                s = Settings()
                s.ensure_dirs()
                db = HRDatabase(s.hr_target)
                if not db.has_data():
                    db = build_database(s.hr_target, s.as_of)
                    if not s.database_url:
                        generate_sample_docs(s.sample_docs_dir, db, s.as_of)
                app.state.runner = HRRunner(AgentContext.build(s))
    return app.state.runner


app = FastAPI(title="HR Intelligence 360 API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=[o for o in os.getenv("HR360_CORS_ORIGINS", "http://localhost:5173").split(",") if o],
                   allow_methods=["*"], allow_headers=["*"], allow_credentials=False)


def shape(res: dict, p: Principal) -> dict:
    """Return only the state fields the caller's role may see."""
    keys = list(PUBLIC_KEYS)
    if role_can(p.internal_role, "run_audit"):
        keys += STAFF_KEYS
    elif p.internal_role == "pm":
        keys += PM_KEYS
    state = {k: res["state"][k] for k in keys if k in res["state"]}
    interrupt = res.get("interrupt")
    if interrupt and not role_can(p.internal_role, "run_workflow"):
        interrupt = {"type": interrupt["type"], "request_id": interrupt["request_id"]}
    return {"request_id": res["request_id"], "status": res["status"], "interrupt": interrupt,
            "final_response": res.get("final_response"), "state": state}


def can_view(p: Principal, req_user: str | None) -> bool:
    return role_can(p.internal_role, "run_audit") or req_user == p.actor_id


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).name)[:120] or "file"


# ------------------------------------------------------------------ endpoints
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/me")
def me(p: Principal = Depends(get_principal)):
    return {"subject": p.subject, "portal_role": p.portal_role, "role": p.internal_role, "employee_id": p.employee_id,
            "permissions": sorted(PERMISSIONS[p.internal_role])}


@app.post("/api/requests")
async def create_request(query: str = Form(..., max_length=2000), files: list[UploadFile] = File(default=[]),
                         p: Principal = Depends(get_principal), runner: HRRunner = Depends(get_runner)):
    if files and not role_can(p.internal_role, "document_upload"):
        raise HTTPException(403, "Your role cannot upload documents")
    saved: list[str] = []
    if files:
        dest = Path(runner.ctx.settings.sample_docs_dir).parent / "uploads" / uuid.uuid4().hex[:10]
        dest.mkdir(parents=True, exist_ok=True)
        for f in files:
            if Path(f.filename or "").suffix.lower() not in ALLOWED_EXT:
                raise HTTPException(400, f"Unsupported file type: {f.filename}")
            data = await f.read(MAX_UPLOAD + 1)
            if len(data) > MAX_UPLOAD:
                raise HTTPException(413, f"{f.filename} exceeds 15 MB")
            path = dest / _safe_name(f.filename or "file")
            path.write_bytes(data)
            saved.append(str(path))
    res = await _run(runner, query, p, saved)
    return shape(res, p)


async def _run(runner, query, p, files):
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(runner.run, query, p.actor_id, p.internal_role, files)


@app.get("/api/requests")
def list_requests(status: str | None = None, p: Principal = Depends(get_principal), runner: HRRunner = Depends(get_runner)):
    own_only = None if role_can(p.internal_role, "run_audit") else p.actor_id
    return runner.list_requests(status=status, user_id=own_only)


@app.get("/api/requests/{request_id}")
def get_request(request_id: str, p: Principal = Depends(get_principal), runner: HRRunner = Depends(get_runner)):
    owner = next((r["user_id"] for r in runner.list_requests(limit=500) if r["request_id"] == request_id), None)
    if owner is None or not can_view(p, owner):
        raise HTTPException(404, "Request not found")
    return shape(runner.get(request_id), p)


class Decision(BaseModel):
    approved: bool
    comment: str = ""
    approved_draft_ids: list[str] | None = None


@app.post("/api/requests/{request_id}/decision")
def decide(request_id: str, body: Decision, p: Principal = Depends(require_permission("approve_actions")),
           runner: HRRunner = Depends(get_runner)):
    snap = runner.get(request_id)
    if snap["status"] != "awaiting_approval":
        raise HTTPException(409, "Request is not awaiting approval")
    res = runner.resume(request_id, p.actor_id, p.internal_role, body.approved, body.comment[:500], body.approved_draft_ids)
    return shape(res, p)


@app.get("/api/approvals")
def approvals(p: Principal = Depends(require_permission("run_workflow")), runner: HRRunner = Depends(get_runner)):
    out = []
    for r in runner.list_requests("awaiting_approval"):
        snap = runner.get(r["request_id"])
        if snap["status"] == "awaiting_approval":
            out.append({**r, "drafts": snap["interrupt"]["drafts"]})
    return out


@app.get("/api/employees")
def employees(p: Principal = Depends(require_permission("view_employee_masked")), runner: HRRunner = Depends(get_runner)):
    full = role_can(p.internal_role, "view_employee_full")
    runner.ctx.audit_log.record("view_employee_directory", actor=p.actor_id, role=p.internal_role, agent="api", detail={"full": full})
    df = public_employee_view(runner.ctx.db.employees(), full).fillna("")
    return {"full": full, "rows": df.to_dict(orient="records")}


@app.get("/api/audit-log")
def audit_log(limit: int = 200, p: Principal = Depends(require_permission("view_audit_log")), runner: HRRunner = Depends(get_runner)):
    return runner.ctx.audit_log.fetch(limit=min(limit, 500))


@app.get("/api/requests/{request_id}/report/{kind}")
def report(request_id: str, kind: str, p: Principal = Depends(get_principal), runner: HRRunner = Depends(get_runner)):
    if kind not in ("pdf", "csv"):
        raise HTTPException(404)
    owner = next((r["user_id"] for r in runner.list_requests(limit=500) if r["request_id"] == request_id), None)
    if owner is None or not can_view(p, owner) or not role_can(p.internal_role, "run_audit"):
        raise HTTPException(404, "Report not found")
    path = (runner.get(request_id)["state"].get("report_paths") or {}).get(kind)
    if not path or not Path(path).exists():
        raise HTTPException(404, "Report not found")
    return FileResponse(path, filename=Path(path).name)
