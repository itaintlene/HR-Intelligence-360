"""Approved emails: Resend integration + safety rules (HTTP is mocked)."""
import pytest

from hr360.email_sender import SendResult, send_email


class FakeResp:
    def __init__(self, code=200, body=None):
        self.status_code, self._b, self.text = code, body or {"id": "em_123"}, "x"

    def json(self):
        return self._b


@pytest.fixture()
def calls(monkeypatch):
    sent = []

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append({"url": url, "headers": headers, "json": json})
        return FakeResp()
    monkeypatch.setattr("hr360.email_sender.httpx.post", fake_post)
    for k in ("RESEND_API_KEY", "HR360_EMAIL_REDIRECT_TO", "HR360_EMAIL_LIVE", "RESEND_FROM"):
        monkeypatch.delenv(k, raising=False)
    return sent


def test_nothing_sent_without_api_key(calls):
    assert send_email("a@b.com", "s", "b", "EMP-1", "k").delivery == "not_sent" and not calls


def test_key_alone_never_emails_employees(calls, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_x")
    assert send_email("emp@corp.com", "s", "b", "EMP-1", "k").delivery == "not_sent" and not calls


def test_redirect_mode_sends_only_to_redirect_address(calls, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_x")
    monkeypatch.setenv("HR360_EMAIL_REDIRECT_TO", "qa@example.org")
    r = send_email("emp@corp.com", "Docs pending", "hello", "EMP-1035", "req-draft")
    assert r == SendResult("sent", "em_123", "", "qa@example.org")
    p = calls[0]
    assert p["json"]["to"] == ["qa@example.org"] and "EMP-1035" in p["json"]["subject"] and "emp@corp.com" not in str(p["json"])
    assert p["headers"]["Idempotency-Key"] == "req-draft" and p["headers"]["Authorization"] == "Bearer re_x"


def test_live_mode_sends_to_employee(calls, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_x")
    monkeypatch.setenv("HR360_EMAIL_LIVE", "true")
    assert send_email("emp@corp.com", "s", "b", "EMP-1", "k").to == "emp@corp.com" and calls[0]["json"]["to"] == ["emp@corp.com"]


def test_provider_error_is_reported_not_raised(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_x")
    monkeypatch.setenv("HR360_EMAIL_REDIRECT_TO", "qa@example.org")
    monkeypatch.setattr("hr360.email_sender.httpx.post", lambda *a, **k: FakeResp(403, {}))
    assert send_email("e@c.com", "s", "b", "EMP-1", "k").delivery == "failed"


def test_approval_flow_sends_only_after_approval(runner, calls, monkeypatch, ctx):
    monkeypatch.setenv("RESEND_API_KEY", "re_x")
    monkeypatch.setenv("HR360_EMAIL_REDIRECT_TO", "qa@example.org")
    r = runner.run("Run onboarding for EMP-1035", "hr.1", "hr_staff")
    assert r["status"] == "awaiting_approval" and not calls          # drafting never sends
    done = runner.resume(r["request_id"], "mgr", "hr_manager", True)
    assert len(calls) == 1 and calls[0]["json"]["to"] == ["qa@example.org"]
    assert [d["status"] for d in done["state"]["generated_email_drafts"]] == ["sent"]
    from sqlalchemy import text
    with ctx.audit_log.engine.connect() as c:
        row = c.execute(text("SELECT delivery, provider_id FROM outbox WHERE request_id=:r"), {"r": r["request_id"]}).first()
    assert row == ("sent", "em_123")


def test_rejected_or_unauthorised_approval_sends_nothing(runner, calls, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_x")
    monkeypatch.setenv("HR360_EMAIL_REDIRECT_TO", "qa@example.org")
    r = runner.run("Run onboarding for EMP-1035", "hr.1", "hr_staff")
    runner.resume(r["request_id"], "staff", "hr_staff", True)
    r2 = runner.run("Run onboarding for EMP-1035", "hr.1", "hr_staff")
    runner.resume(r2["request_id"], "mgr", "hr_manager", False)
    assert not calls
