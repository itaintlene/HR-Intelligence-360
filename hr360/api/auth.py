"""Authentication: verifies Clerk session JWTs and maps them to an internal Principal.

Clerk setup (see docs/CLERK_SETUP.md): the session token carries the user's public metadata as
claim ``metadata`` -> {"role": "employee"|"hr"|"pm", "employee_id": "EMP-1012", "hr_level": "manager"?}.
Roles are assigned by an admin in the Clerk dashboard; users can never set their own.

HR360_AUTH_MODE=dev enables header-based fake auth for local development/tests only.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient

log = logging.getLogger("hr360.auth")
PORTAL_ROLES = ("employee", "hr", "pm")


@dataclass(frozen=True)
class Principal:
    subject: str            # Clerk user id (or dev id)
    portal_role: str        # employee | hr | pm
    internal_role: str      # RBAC role used by the agent graph
    employee_id: str | None
    display_name: str = ""

    @property
    def actor_id(self) -> str:
        """Pseudonymous id used in state/audit log (employee id preferred over Clerk id)."""
        return self.employee_id or self.subject


def to_internal_role(portal_role: str, metadata: dict) -> str:
    if portal_role == "hr":
        return "admin" if metadata.get("hr_level") == "admin" else (
            "hr_manager" if metadata.get("hr_level") == "manager" else "hr_staff")
    return portal_role  # employee | pm


def _principal_from_metadata(sub: str, md: dict, name: str = "") -> Principal:
    role = md.get("role")
    if role not in PORTAL_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No HR360 role assigned to this account. Ask an admin.")
    return Principal(sub, role, to_internal_role(role, md), md.get("employee_id"), name)


_jwks: PyJWKClient | None = None


def _verify_clerk(token: str) -> dict:
    global _jwks
    issuer = os.getenv("CLERK_ISSUER", "").rstrip("/")
    if not issuer:
        raise HTTPException(500, "Server misconfigured: CLERK_ISSUER not set")
    if _jwks is None:
        _jwks = PyJWKClient(os.getenv("CLERK_JWKS_URL") or f"{issuer}/.well-known/jwks.json", cache_keys=True)
    try:
        key = _jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], issuer=issuer, options={"require": ["exp", "iat", "sub"]})
    except Exception as exc:  # expired, bad signature, wrong issuer, JWKS unreachable...
        log.info("JWT rejected: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session") from exc
    allowed = [p for p in os.getenv("CLERK_AUTHORIZED_PARTIES", "").split(",") if p]
    if allowed and claims.get("azp") not in allowed:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unexpected token origin")
    return claims


def get_principal(authorization: str | None = Header(default=None), x_dev_user: str | None = Header(default=None),
                  x_dev_role: str | None = Header(default=None), x_dev_employee: str | None = Header(default=None),
                  x_dev_level: str | None = Header(default=None)) -> Principal:
    if os.getenv("HR360_AUTH_MODE", "clerk") == "dev":
        if not x_dev_user or not x_dev_role:
            raise HTTPException(401, "Dev mode: send X-Dev-User and X-Dev-Role headers")
        md = {"role": x_dev_role, "employee_id": x_dev_employee, "hr_level": x_dev_level}
        return _principal_from_metadata(x_dev_user, md, x_dev_user)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    claims = _verify_clerk(authorization.split(" ", 1)[1])
    md = claims.get("metadata") or {}
    return _principal_from_metadata(claims["sub"], md if isinstance(md, dict) else {}, claims.get("name", ""))


def require_permission(permission: str):
    from hr360.security.rbac import role_can

    def dep(p: Principal = Depends(get_principal)) -> Principal:
        if not role_can(p.internal_role, permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Role '{p.portal_role}' lacks '{permission}'")
        return p
    return dep
