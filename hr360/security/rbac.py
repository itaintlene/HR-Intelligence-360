"""Basic role-based access control. Roles/permissions are data, not scattered ifs."""
from __future__ import annotations

from dataclasses import dataclass

ROLES = ("employee", "pm", "hr_staff", "hr_manager", "admin")

_ALL = {"policy_query", "submit_standup", "view_own_work"}
_STAFF = _ALL | {"document_upload", "run_audit", "run_workflow", "view_employee_masked", "view_team_leave",
                 "view_project_status", "view_person_record", "review_evidence"}
PERMISSIONS: dict[str, set[str]] = {
    "employee": set(_ALL),
    # project manager: policy Q&A, leave + project status scoped to their own team/projects (never approves HR actions)
    "pm": _ALL | {"view_team_leave", "view_project_status", "review_evidence"},
    "hr_staff": set(_STAFF),
    "hr_manager": _STAFF | {"view_employee_full", "approve_actions", "manage_projects"},
    "admin": _STAFF | {"view_employee_full", "approve_actions", "view_audit_log", "manage_users", "manage_settings", "manage_projects"},
}

# task type -> permission required
TASK_PERMISSION = {
    "policy_question": "policy_query",
    "document_audit": "document_upload",
    "onboarding": "run_workflow",
    "audit_summary": "run_audit",
    "leave_summary": "view_team_leave",
    "project_status": "view_project_status",
    "person_record": "view_person_record",
}


@dataclass(frozen=True)
class User:
    user_id: str
    role: str = "employee"

    def can(self, permission: str) -> bool:
        return role_can(self.role, permission)


def role_can(role: str, permission: str) -> bool:
    return permission in PERMISSIONS.get(role, set())


def authorize_task(role: str, task_type: str) -> tuple[bool, str]:
    perm = TASK_PERMISSION.get(task_type)
    if perm is None or role_can(role, perm):
        return True, ""
    return False, f"Role '{role}' is not permitted to run '{task_type}' (requires '{perm}')."


def mask_email(email: str | None) -> str:
    if not isinstance(email, str) or "@" not in email:  # missing values arrive as None / NaN
        return "***"
    local, domain = email.split("@", 1)
    return f"{local[:1]}***@{domain}"


def mask_id(value: str | None) -> str:
    if not isinstance(value, str) or not value:
        return ""
    return "*" * max(len(value) - 4, 0) + value[-4:]
