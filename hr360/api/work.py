"""Work-tracking API: stand-ups, projects, contribution evidence, GitHub import.

Access model
  employee : submit own stand-ups, upload proof, see own record + projects they belong to
  pm       : everything about the projects they manage (status, members' stand-ups, evidence review)
  hr       : all projects and individual work records (every record view is audit-logged)
There is intentionally NO endpoint that scores, ranks or orders people.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from hr360.api.auth import Principal, get_principal, require_permission
from hr360.graph.runner import HRRunner
from hr360.security.rbac import role_can
from hr360.work import analytics

router = APIRouter(prefix="/api/work", tags=["work"])
EVIDENCE_EXT = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".txt", ".md", ".csv"}
MAX_EVIDENCE = 10 * 1024 * 1024
EDIT_WINDOW_DAYS = 7


def _runner() -> HRRunner:
    from hr360.api.main import get_runner
    return get_runner()


def _repo(runner: HRRunner):
    from hr360.work.repo import WorkRepo
    if "work_repo" not in runner.ctx.extras:
        runner.ctx.extras["work_repo"] = WorkRepo(runner.ctx.db.engine)
    return runner.ctx.extras["work_repo"]


def _agent(runner: HRRunner):
    from hr360.agents.work_agent import WorkInsightsAgent
    if "work_agent" not in runner.ctx.extras:
        runner.ctx.extras["work_agent"] = WorkInsightsAgent(runner.ctx)
    return runner.ctx.extras["work_agent"]


def _is_hr(p: Principal) -> bool:
    return role_can(p.internal_role, "view_person_record")


def _manages(p: Principal, project: dict) -> bool:
    return p.internal_role == "pm" and bool(p.employee_id) and project["manager_employee_id"] == p.employee_id


def _need_project(repo, project_id: str) -> dict:
    proj = repo.project(project_id)
    if proj is None:
        raise HTTPException(404, "Project not found")
    return proj


def _need_employee_id(p: Principal) -> str:
    if not p.employee_id:
        raise HTTPException(400, "Your account is not linked to an employee ID yet. Ask an admin to set it.")
    return p.employee_id


def _audit(runner: HRRunner, p: Principal, action: str, detail: dict) -> None:
    runner.ctx.audit_log.record(action, actor=p.actor_id, role=p.internal_role, agent="work_api", detail=detail)


# ------------------------------------------------------------------------------------------------ projects
@router.get("/projects")
def list_projects(p: Principal = Depends(get_principal), runner: HRRunner = Depends(_runner)):
    repo, ctx = _repo(runner), runner.ctx
    df = repo.projects()
    mine = set(repo.projects_of_member(p.employee_id)) if p.employee_id else set()
    leaves = ctx.db.leave_requests()
    out = []
    for r in df.to_dict("records"):
        managed = _manages(p, r)
        if not (_is_hr(p) or managed or r["project_id"] in mine):
            continue
        row = analytics.clean({k: r[k] for k in ("project_id", "name", "description", "manager_employee_id", "target_date", "status", "repo")})
        row["i_manage"] = managed
        row["i_am_member"] = r["project_id"] in mine
        if _is_hr(p) or managed:
            s = analytics.project_status(repo, leaves, r["project_id"], ctx.settings.as_of)
            row.update(progress=s["progress"], open_blockers=len(s["blockers"]), flags=len(s["flags"]), members=len(s["members"]))
        out.append(row)
    return out


class MemberIn(BaseModel):
    employee_id: str = Field(pattern=r"^EMP-\d{3,6}$")
    role_on_project: str = "contributor"


class MilestoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    due_date: date
    weight: float = 1.0


class ProjectIn(BaseModel):
    project_id: str | None = Field(default=None, pattern=r"^PRJ-\d{2,5}$")
    name: str = Field(min_length=2, max_length=120)
    description: str = ""
    manager_employee_id: str = Field(pattern=r"^EMP-\d{3,6}$")
    start_date: date
    target_date: date
    repo: str | None = Field(default=None, pattern=r"^[\w.-]+/[\w.-]+$")
    members: list[MemberIn] = []
    milestones: list[MilestoneIn] = []


@router.post("/projects")
def create_project(body: ProjectIn, p: Principal = Depends(require_permission("manage_projects")), runner: HRRunner = Depends(_runner)):
    repo, db = _repo(runner), runner.ctx.db
    if body.target_date <= body.start_date:
        raise HTTPException(422, "target_date must be after start_date")
    for emp in {body.manager_employee_id, *[m.employee_id for m in body.members]}:
        if db.get_employee(emp) is None:
            raise HTTPException(422, f"{emp} does not exist in the HR database")
    existing = repo.projects()["project_id"].tolist()
    pid = body.project_id or f"PRJ-{max([int(x.split('-')[1]) for x in existing] + [100]) + 1}"
    if pid in existing:
        raise HTTPException(409, f"{pid} already exists")
    repo.create_project({"project_id": pid, "name": body.name, "description": body.description, "manager_employee_id": body.manager_employee_id,
                         "start_date": body.start_date.isoformat(), "target_date": body.target_date.isoformat(), "status": "active", "repo": body.repo},
                        [m.model_dump() for m in body.members],
                        [{"name": m.name, "due_date": m.due_date.isoformat(), "status": "todo", "done_on": None, "weight": m.weight} for m in body.milestones])
    _audit(runner, p, "project_created", {"project_id": pid, "members": len(body.members)})
    return {"project_id": pid}


@router.put("/projects/{project_id}/members")
def put_member(project_id: str, body: MemberIn, p: Principal = Depends(get_principal), runner: HRRunner = Depends(_runner)):
    repo = _repo(runner)
    proj = _need_project(repo, project_id)
    if not (role_can(p.internal_role, "manage_projects") or _manages(p, proj)):
        raise HTTPException(403, "Only the project's manager or HR leadership can change members")
    if runner.ctx.db.get_employee(body.employee_id) is None:
        raise HTTPException(422, f"{body.employee_id} does not exist in the HR database")
    repo.add_member(project_id, body.employee_id, body.role_on_project)
    _audit(runner, p, "project_member_set", {"project_id": project_id, "employee_id": body.employee_id})
    return {"ok": True}


class MilestoneUpdate(BaseModel):
    status: Literal["todo", "in_progress", "done"]


@router.patch("/milestones/{milestone_id}")
def set_milestone(milestone_id: str, body: MilestoneUpdate, p: Principal = Depends(get_principal), runner: HRRunner = Depends(_runner)):
    repo = _repo(runner)
    pid = milestone_id.rsplit("-M", 1)[0]
    proj = _need_project(repo, pid)
    if not (role_can(p.internal_role, "manage_projects") or _manages(p, proj)):
        raise HTTPException(403, "Only the project's manager or HR leadership can update milestones")
    if not repo.set_milestone_status(milestone_id, body.status, runner.ctx.settings.as_of.isoformat() if body.status == "done" else None):
        raise HTTPException(404, "Milestone not found")
    _audit(runner, p, "milestone_updated", {"milestone_id": milestone_id, "status": body.status})
    return {"ok": True}


@router.get("/projects/{project_id}")
def project_detail(project_id: str, window: int = 10, p: Principal = Depends(get_principal), runner: HRRunner = Depends(_runner)):
    repo = _repo(runner)
    proj = _need_project(repo, project_id)
    if not (_is_hr(p) or _manages(p, proj)):
        raise HTTPException(404, "Project not found")           # members/others must not learn the project exists
    _audit(runner, p, "view_project_status", {"project_id": project_id})
    return analytics.project_status(repo, runner.ctx.db.leave_requests(), project_id, runner.ctx.settings.as_of, min(max(window, 5), 30))


@router.get("/projects/{project_id}/people/{employee_id}")
def project_person(project_id: str, employee_id: str, p: Principal = Depends(get_principal), runner: HRRunner = Depends(_runner)):
    repo = _repo(runner)
    proj = _need_project(repo, project_id)
    if not (_is_hr(p) or _manages(p, proj)):
        raise HTTPException(404, "Project not found")
    if employee_id not in repo.members(project_id)["employee_id"].tolist():
        raise HTTPException(404, "Not a member of this project")
    _audit(runner, p, "view_person_record", {"employee_id": employee_id, "project_id": project_id})
    return analytics.person_record(repo, runner.ctx.db.leave_requests(), employee_id, runner.ctx.settings.as_of, 20, project_id)


# ------------------------------------------------------------------------------------------------ stand-ups
class StandupIn(BaseModel):
    project_id: str = Field(pattern=r"^PRJ-\d{2,5}$")
    entry_date: date | None = None
    done_text: str = Field(default="", max_length=2000)
    planned_text: str = Field(default="", max_length=2000)
    blockers_text: str = Field(default="", max_length=1000)
    blocker_status: Literal["none", "open", "resolved"] = "none"
    self_progress: int | None = Field(default=None, ge=0, le=100)
    hours: float | None = Field(default=None, ge=0, le=24)


@router.post("/standups")
def submit_standup(body: StandupIn, p: Principal = Depends(require_permission("submit_standup")), runner: HRRunner = Depends(_runner)):
    emp = _need_employee_id(p)
    repo, today = _repo(runner), runner.ctx.settings.as_of
    _need_project(repo, body.project_id)
    if emp not in repo.members(body.project_id)["employee_id"].tolist():
        raise HTTPException(403, "You are not a member of this project")
    day = body.entry_date or today
    if day > today or (today - day).days > EDIT_WINDOW_DAYS:
        raise HTTPException(422, f"Stand-ups can be entered for today or the last {EDIT_WINDOW_DAYS} days only")
    if not body.done_text.strip() and not body.planned_text.strip():
        raise HTTPException(422, "Fill in at least what you did or what you plan to do")
    blockers = body.blockers_text.strip()
    status = body.blocker_status if blockers else "none"
    if blockers and status == "none":
        status = "open"
    sid = repo.upsert_standup(emp, body.project_id, day.isoformat(), body.done_text.strip(), body.planned_text.strip(), blockers, status,
                              body.self_progress, body.hours)
    _audit(runner, p, "standup_submitted", {"standup_id": sid})
    return {"standup_id": sid, "entry_date": day.isoformat()}


@router.get("/me")
def my_record(days: int = 20, p: Principal = Depends(require_permission("view_own_work")), runner: HRRunner = Depends(_runner)):
    emp = _need_employee_id(p)
    return analytics.person_record(_repo(runner), runner.ctx.db.leave_requests(), emp, runner.ctx.settings.as_of, min(max(days, 5), 60))


# ------------------------------------------------------------------------------------------------ evidence
@router.post("/standups/{standup_id}/evidence")
async def upload_evidence(standup_id: str, file: UploadFile = File(...), description: str = Form("", max_length=500),
                          p: Principal = Depends(require_permission("submit_standup")), runner: HRRunner = Depends(_runner)):
    repo = _repo(runner)
    su = repo.get_standup(standup_id)
    if su is None or su["employee_id"] != p.employee_id:
        raise HTTPException(404, "Stand-up not found")           # only the author can attach proof
    if Path(file.filename or "").suffix.lower() not in EVIDENCE_EXT:
        raise HTTPException(400, f"Unsupported file type (allowed: {', '.join(sorted(EVIDENCE_EXT))})")
    data = await file.read(MAX_EVIDENCE + 1)
    if len(data) > MAX_EVIDENCE:
        raise HTTPException(413, "File exceeds 10 MB")
    from hr360.api.main import _safe_name
    dest = Path(runner.ctx.settings.sample_docs_dir).parent / "evidence" / uuid.uuid4().hex[:10]
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError:
        dest = Path("/tmp/hr360/evidence") / uuid.uuid4().hex[:10]
        dest.mkdir(parents=True, exist_ok=True)
    path = dest / _safe_name(file.filename or "proof")
    path.write_bytes(data)
    from starlette.concurrency import run_in_threadpool
    analysis = await run_in_threadpool(_agent(runner).analyze_evidence, path, description)
    row = repo.add_evidence(su, path.name, str(path), description, analysis)
    _audit(runner, p, "evidence_uploaded", {"evidence_id": row["evidence_id"], "method": analysis["method"], "injection_lines_removed": len(analysis["injection_flags"])})
    return {"evidence_id": row["evidence_id"], "ai_summary": analysis["summary"], "analysis_method": analysis["method"],
            "injection_flags": analysis["injection_flags"], "review_status": "pending",
            "note": "AI-generated summary - not verified. A manager or HR reviewer confirms it."}


class ReviewIn(BaseModel):
    status: Literal["verified", "disputed", "pending"]


@router.patch("/evidence/{evidence_id}/review")
def review_evidence(evidence_id: str, body: ReviewIn, p: Principal = Depends(require_permission("review_evidence")), runner: HRRunner = Depends(_runner)):
    repo = _repo(runner)
    ev = repo.get_evidence(evidence_id)
    if ev is None:
        raise HTTPException(404, "Evidence not found")
    if not (_is_hr(p) or _manages(p, _need_project(repo, ev["project_id"]))):
        raise HTTPException(404, "Evidence not found")
    if ev["employee_id"] == p.employee_id:
        raise HTTPException(409, "You cannot review your own evidence")
    repo.review_evidence(evidence_id, body.status, p.actor_id)
    _audit(runner, p, "evidence_reviewed", {"evidence_id": evidence_id, "status": body.status})
    return {"ok": True}


# ------------------------------------------------------------------------------------------------ people (HR)
@router.get("/people/{employee_id}")
def person(employee_id: str, days: int = 20, p: Principal = Depends(require_permission("view_person_record")), runner: HRRunner = Depends(_runner)):
    if runner.ctx.db.get_employee(employee_id) is None:
        raise HTTPException(404, "Employee not found")
    _audit(runner, p, "view_person_record", {"employee_id": employee_id})
    return analytics.person_record(_repo(runner), runner.ctx.db.leave_requests(), employee_id, runner.ctx.settings.as_of, min(max(days, 5), 60))


# ------------------------------------------------------------------------------------------------ GitHub
class IdentityIn(BaseModel):
    github_login: str = Field(pattern=r"^[A-Za-z0-9-]{1,39}$")
    employee_id: str = Field(pattern=r"^EMP-\d{3,6}$")


@router.post("/github/identities")
def map_identity(body: IdentityIn, p: Principal = Depends(require_permission("manage_projects")), runner: HRRunner = Depends(_runner)):
    if runner.ctx.db.get_employee(body.employee_id) is None:
        raise HTTPException(422, f"{body.employee_id} does not exist")
    _repo(runner).map_identity(body.github_login, body.employee_id)
    _audit(runner, p, "github_identity_mapped", body.model_dump())
    return {"ok": True}


class GithubEvent(BaseModel):
    event_id: str = Field(max_length=80)
    github_login: str = Field(max_length=39)
    repo: str | None = None
    event_type: Literal["commit", "pr_opened", "pr_merged", "review", "issue_closed"]
    title: str = ""
    url: str | None = None
    event_ts: str
    additions: int = 0
    deletions: int = 0


class GithubImport(BaseModel):
    events: list[GithubEvent] = Field(max_length=1000)


@router.post("/github/events")
def import_events(body: GithubImport, p: Principal = Depends(require_permission("manage_projects")), runner: HRRunner = Depends(_runner)):
    """Bulk, idempotent import. A GitHub webhook / Action can POST here later (same payload shape)."""
    res = _repo(runner).import_github_events([e.model_dump() for e in body.events])
    _audit(runner, p, "github_events_imported", res)
    return res
