"""Admin-only endpoints: user/role management (via Clerk), runtime settings, system status.
Deliberately not linked from the main navigation; reachable at /admin in the web app for admins only."""
from __future__ import annotations

import os
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from hr360 import app_settings
from hr360.api import clerk_admin
from hr360.api.auth import Principal, bootstrap_admin_ids, require_permission
from hr360.graph.runner import HRRunner

router = APIRouter(prefix="/api/admin", tags=["admin"])
EMP_RX = re.compile(r"^EMP-\d{3,6}$")


def _runner() -> HRRunner:
    from hr360.api.main import get_runner
    return get_runner()


def _audit(runner: HRRunner, p: Principal, action: str, detail: dict) -> None:
    runner.ctx.audit_log.record(action, actor=p.actor_id, role=p.internal_role, agent="admin", detail=detail)


@router.get("/users")
def users(query: str | None = None, p: Principal = Depends(require_permission("manage_users"))):
    boot = bootstrap_admin_ids()
    out = clerk_admin.list_users(query)
    for u in out:
        u["bootstrap_admin"] = u["id"] in boot
        u["is_you"] = u["id"] == p.subject
    return out


class RoleUpdate(BaseModel):
    role: Literal["employee", "pm", "hr"]
    hr_level: Literal["staff", "manager", "admin"] | None = None
    employee_id: str | None = None


@router.put("/users/{user_id}/role")
def set_role(user_id: str, body: RoleUpdate, p: Principal = Depends(require_permission("manage_users")),
             runner: HRRunner = Depends(_runner)):
    if user_id == p.subject:
        raise HTTPException(409, "You cannot change your own role (ask another admin)")
    if user_id in bootstrap_admin_ids():
        raise HTTPException(409, "This user is a bootstrap admin (set by server config) and cannot be changed here")
    if body.employee_id:
        if not EMP_RX.match(body.employee_id):
            raise HTTPException(422, "employee_id must look like EMP-1234")
        if runner.ctx.db.get_employee(body.employee_id) is None:
            raise HTTPException(422, f"{body.employee_id} does not exist in the HR database")
    if body.role == "pm" and not body.employee_id:
        raise HTTPException(422, "A project manager needs an employee_id (their team is found through it)")
    level = (body.hr_level or "staff") if body.role == "hr" else None
    before = clerk_admin.get_user(user_id)
    after = clerk_admin.set_role(user_id, body.role, level, body.employee_id)
    _audit(runner, p, "admin_set_role", {"target": user_id, "from": {"role": before["role"], "hr_level": before["hr_level"]},
                                         "to": {"role": body.role, "hr_level": level, "employee_id": body.employee_id}})
    return after


@router.get("/settings")
def get_settings(p: Principal = Depends(require_permission("manage_settings")), runner: HRRunner = Depends(_runner)):
    return {**app_settings.get_all(runner.ctx.audit_log.engine), "resend_configured": bool(os.getenv("RESEND_API_KEY"))}


class SettingsUpdate(BaseModel):
    email_mode: Literal["env", "off", "redirect", "live"] | None = None
    email_redirect_to: str | None = None


@router.put("/settings")
def put_settings(body: SettingsUpdate, p: Principal = Depends(require_permission("manage_settings")),
                 runner: HRRunner = Depends(_runner)):
    engine = runner.ctx.audit_log.engine
    changes = body.model_dump(exclude_none=True)
    merged = {**app_settings.get_all(engine), **changes}
    if merged["email_mode"] == "redirect" and not merged["email_redirect_to"]:
        raise HTTPException(422, "Redirect mode needs a redirect email address")
    try:
        for k, v in changes.items():
            app_settings.set_value(engine, k, v, p.actor_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _audit(runner, p, "admin_update_settings", changes)
    return app_settings.get_all(engine)


@router.get("/system")
def system(p: Principal = Depends(require_permission("manage_settings")), runner: HRRunner = Depends(_runner)):
    ctx = runner.ctx
    return {"database": ctx.db.engine.dialect.name, "employees": len(ctx.db.employees()),
            "llm_enabled": ctx.llm.available, "llm_model": os.getenv("HR360_LLM_MODEL"),
            "embeddings": ctx.settings.embeddings_backend, "as_of": ctx.settings.as_of.isoformat(),
            "auth_mode": os.getenv("HR360_AUTH_MODE", "clerk"), "clerk_admin_api": bool(os.getenv("CLERK_SECRET_KEY")),
            "resend_configured": bool(os.getenv("RESEND_API_KEY")), "tracing": os.getenv("LANGSMITH_TRACING") == "true"}
