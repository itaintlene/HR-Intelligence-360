"""Transactional email via Resend (https://resend.com/docs/api-reference/emails/send-email).

Safety rules (only ever reached AFTER a human approval):
* No RESEND_API_KEY                      -> nothing is sent; the email is only recorded in the outbox table.
* HR360_EMAIL_REDIRECT_TO set            -> every email goes to that address instead of the employee (test mode;
                                            required while using synthetic employee addresses / an unverified domain).
* HR360_EMAIL_LIVE=true (and no redirect)-> emails go to the real employee address. Needs a verified Resend domain.
* Otherwise                              -> nothing is sent.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

log = logging.getLogger("hr360.email")
API = "https://api.resend.com/emails"
DEFAULT_FROM = "HR Intelligence 360 <onboarding@resend.dev>"  # Resend's shared sandbox sender (no domain needed)


@dataclass
class SendResult:
    delivery: str            # sent | failed | not_sent
    provider_id: str | None = None
    detail: str = ""
    to: str | None = None


def send_email(to_employee_email: str | None, subject: str, body: str, employee_id: str, idempotency_key: str) -> SendResult:
    key = os.getenv("RESEND_API_KEY")
    redirect = os.getenv("HR360_EMAIL_REDIRECT_TO") or None
    live = os.getenv("HR360_EMAIL_LIVE", "").lower() == "true"
    if not key:
        return SendResult("not_sent", detail="RESEND_API_KEY not configured")
    if redirect:
        to = redirect
        subject = f"[TEST for {employee_id}] {subject}"
        body = f"(Test mode: this email would have been sent to {employee_id}.)\n\n{body}"
    elif live and to_employee_email:
        to = to_employee_email
    else:
        return SendResult("not_sent", detail="live sending disabled (set HR360_EMAIL_REDIRECT_TO or HR360_EMAIL_LIVE=true)")
    try:
        r = httpx.post(API, timeout=20, headers={"Authorization": f"Bearer {key}", "Idempotency-Key": idempotency_key},
                       json={"from": os.getenv("RESEND_FROM", DEFAULT_FROM), "to": [to], "subject": subject, "text": body})
        if r.status_code // 100 == 2:
            return SendResult("sent", r.json().get("id"), to=to)
        log.warning("Resend rejected email: %s %s", r.status_code, r.text[:200])
        return SendResult("failed", detail=f"{r.status_code}: {r.text[:200]}", to=to)
    except httpx.HTTPError as exc:
        return SendResult("failed", detail=f"{type(exc).__name__}: {exc}", to=to)
