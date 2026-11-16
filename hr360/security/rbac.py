"""Basic role-based access control. Roles/permissions are data, not scattered ifs."""
from __future__ import annotations

from dataclasses import dataclass

ROLES = ("employee", "pm", "hr_staff", "hr_manager", "admin")

_STAFF = {"policy_query", "document_upload", "run_audit", "run_workflow", "view_employee_masked", "view_team_leave"}
PERMISSIONS: dict[str, set[str]] = {
    "employee": {"policy_query"},
    # project manager: policy Q&A + leave summary scoped to their direct reports (never approves HR actions)
    "pm": {"policy_query", "view_team_leave"},
    "hr_staff": set(_STAFF),
    "hr_manager": _STAFF | {"view_employee_full", "approve_actions"},
    "admin": _STAFF | {"view_employee_full", "approve_actions", "view_audit_log"},
}

# task type -> permission required
TASK_PERMISSION = {
    "policy_question": "policy_query",
    "document_audit": "document_upload",
    "onboarding": "run_workflow",
    "audit_summary": "run_audit",
    "leave_summary": "view_team_leave",
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
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    return f"{local[:1]}***@{domain}"


def mask_id(value: str | None) -> str:
    if not value:
        return ""
    value = str(value)
    return "*" * max(len(value) - 4, 0) + value[-4:]
