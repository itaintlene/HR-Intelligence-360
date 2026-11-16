"""Minimal Clerk Backend API client for user/role management (requires CLERK_SECRET_KEY, server-side only)."""
from __future__ import annotations

import os

import httpx
from fastapi import HTTPException

BASE = "https://api.clerk.com/v1"


def _headers() -> dict:
    key = os.getenv("CLERK_SECRET_KEY")
    if not key:
        raise HTTPException(503, "User management is not configured: set CLERK_SECRET_KEY on the server")
    return {"Authorization": f"Bearer {key}"}


def _call(method: str, path: str, **kw):
    try:
        r = httpx.request(method, f"{BASE}{path}", headers=_headers(), timeout=20, **kw)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Clerk API unreachable: {type(exc).__name__}") from exc
    if r.status_code // 100 != 2:
        raise HTTPException(502, f"Clerk API error {r.status_code}: {r.text[:200]}")
    return r.json()


def _shape(u: dict) -> dict:
    primary = u.get("primary_email_address_id")
    emails = u.get("email_addresses") or []
    email = next((e["email_address"] for e in emails if e["id"] == primary), emails[0]["email_address"] if emails else "")
    md = u.get("public_metadata") or {}
    return {"id": u["id"], "email": email, "name": " ".join(filter(None, [u.get("first_name"), u.get("last_name")])),
            "role": md.get("role"), "hr_level": md.get("hr_level"), "employee_id": md.get("employee_id"),
            "last_sign_in_at": u.get("last_sign_in_at"), "banned": bool(u.get("banned"))}


def list_users(query: str | None = None, limit: int = 100) -> list[dict]:
    params = {"limit": min(limit, 100), "order_by": "-created_at"}
    if query:
        params["query"] = query
    return [_shape(u) for u in _call("GET", "/users", params=params)]


def get_user(user_id: str) -> dict:
    return _shape(_call("GET", f"/users/{user_id}"))


def set_role(user_id: str, role: str, hr_level: str | None, employee_id: str | None) -> dict:
    """Merge role fields into public metadata (null removes a key)."""
    body = {"public_metadata": {"role": role, "hr_level": hr_level if role == "hr" else None,
                                "employee_id": employee_id or None}}
    return _shape(_call("PATCH", f"/users/{user_id}/metadata", json=body))
