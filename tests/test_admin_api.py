"""Admin API: default-employee auth, bootstrap admin, role management (Clerk mocked), settings."""
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from hr360.api.main import app
from hr360.graph.runner import HRRunner


class FakeClerk:
    """In-memory stand-in for hr360.api.clerk_admin."""

    def __init__(self):
        self.users = {
            "user_a": {"id": "user_a", "email": "a@x.com", "name": "A", "role": None, "hr_level": None, "employee_id": None,
                       "last_sign_in_at": None, "banned": False},
            "user_admin": {"id": "user_admin", "email": "adm@x.com", "name": "Adm", "role": "hr", "hr_level": "admin",
                           "employee_id": None, "last_sign_in_at": None, "banned": False},
        }
        self.calls = []

    def list_users(self, query=None, limit=100):
        return [dict(u) for u in self.users.values()]

    def get_user(self, uid):
        return dict(self.users[uid])

    def set_role(self, uid, role, hr_level, employee_id):
        self.calls.append((uid, role, hr_level, employee_id))
        self.users[uid].update(role=role, hr_level=hr_level, employee_id=employee_id)
        return dict(self.users[uid])


@pytest.fixture()
def clerk(monkeypatch):
    fake = FakeClerk()
    for name in ("list_users", "get_user", "set_role"):
        monkeypatch.setattr(f"hr360.api.clerk_admin.{name}", getattr(fake, name))
    return fake


@pytest.fixture()
def client(ctx, monkeypatch):
    monkeypatch.setenv("HR360_AUTH_MODE", "dev")
    monkeypatch.delenv("HR360_BOOTSTRAP_ADMIN_IDS", raising=False)
    app.state.runner = HRRunner(ctx, MemorySaver())
    return TestClient(app)


def H(role="hr", user="user_admin", level="admin", emp=None):
    h = {"X-Dev-User": user, "X-Dev-Role": role}
    if level:
        h["X-Dev-Level"] = level
    if emp:
        h["X-Dev-Employee"] = emp
    return h


@pytest.mark.parametrize("headers", [H("employee", level=None), H("pm", level=None, emp="EMP-1001"), H("hr", level=None),
                                     H("hr", level="manager")])
def test_non_admins_cannot_use_admin_endpoints(client, clerk, headers):
    for method, path in (("get", "/api/admin/users"), ("get", "/api/admin/settings"), ("get", "/api/admin/system")):
        assert getattr(client, method)(path, headers=headers).status_code == 403
    assert client.put("/api/admin/users/user_a/role", json={"role": "hr"}, headers=headers).status_code == 403
    assert not clerk.calls


def test_admin_lists_users_with_flags(client, clerk):
    rows = client.get("/api/admin/users", headers=H()).json()
    assert {r["id"] for r in rows} == {"user_a", "user_admin"} and [r for r in rows if r["is_you"]][0]["id"] == "user_admin"


def test_admin_assigns_roles_and_audits(client, clerk, ctx):
    r = client.put("/api/admin/users/user_a/role", json={"role": "pm", "employee_id": "EMP-1001"}, headers=H())
    assert r.status_code == 200 and clerk.calls[-1] == ("user_a", "pm", None, "EMP-1001")
    r = client.put("/api/admin/users/user_a/role", json={"role": "hr", "hr_level": "manager"}, headers=H())
    assert clerk.calls[-1] == ("user_a", "hr", "manager", None)
    assert any(e["action"] == "admin_set_role" and "user_a" in e["detail"] for e in ctx.audit_log.fetch(limit=20))


def test_role_update_validation(client, clerk):
    put = lambda body, uid="user_a": client.put(f"/api/admin/users/{uid}/role", json=body, headers=H())  # noqa: E731
    assert put({"role": "superuser"}).status_code == 422
    assert put({"role": "pm"}).status_code == 422                                   # pm needs an employee id
    assert put({"role": "employee", "employee_id": "bad id"}).status_code == 422
    assert put({"role": "employee", "employee_id": "EMP-9999"}).status_code == 422  # not in HR database
    assert put({"role": "hr", "hr_level": "root"}).status_code == 422
    assert put({"role": "employee"}, uid="user_admin").status_code == 409          # cannot demote yourself
    assert not clerk.calls


def test_default_role_is_employee_and_bootstrap_admin_can_reach_admin(client, clerk, monkeypatch):
    plain = client.get("/api/me", headers={"X-Dev-User": "user_new", "X-Dev-Role": "none"}).json()
    assert plain["portal_role"] == "employee"
    assert client.get("/api/admin/users", headers={"X-Dev-User": "user_new", "X-Dev-Role": "none"}).status_code == 403
    monkeypatch.setenv("HR360_BOOTSTRAP_ADMIN_IDS", "user_new, other")
    boot = {"X-Dev-User": "user_new", "X-Dev-Role": "none"}
    assert client.get("/api/me", headers=boot).json()["role"] == "admin"
    assert client.get("/api/admin/users", headers=boot).status_code == 200
    # bootstrap admins are protected from being edited via the UI
    assert client.put("/api/admin/users/user_new/role", json={"role": "employee"}, headers=H()).status_code == 409


def test_settings_roundtrip_and_validation(client, clerk, ctx):
    assert client.get("/api/admin/settings", headers=H()).json()["email_mode"] == "env"
    assert client.put("/api/admin/settings", json={"email_mode": "redirect"}, headers=H()).status_code == 422  # needs address
    assert client.put("/api/admin/settings", json={"email_mode": "redirect", "email_redirect_to": "nope"}, headers=H()).status_code == 422
    ok = client.put("/api/admin/settings", json={"email_mode": "redirect", "email_redirect_to": "qa@example.org"}, headers=H())
    assert ok.status_code == 200 and ok.json()["email_redirect_to"] == "qa@example.org"
    assert client.put("/api/admin/settings", json={"email_mode": "off"}, headers=H()).json()["email_mode"] == "off"


def test_email_settings_from_admin_page_control_sending(client, clerk, runner, monkeypatch):
    sent = []

    class R:
        status_code = 200
        text = ""

        def json(self):
            return {"id": "em_1"}
    monkeypatch.setattr("hr360.email_sender.httpx.post", lambda *a, **k: sent.append(k["json"]) or R())
    monkeypatch.setenv("RESEND_API_KEY", "re_x")
    monkeypatch.setenv("HR360_EMAIL_LIVE", "true")        # env says live, but the admin setting must win
    app.state.runner = runner
    c = TestClient(app)
    c.put("/api/admin/settings", json={"email_mode": "off"}, headers=H())
    r = runner.run("Run onboarding for EMP-1035", "hr.1", "hr_staff")
    runner.resume(r["request_id"], "mgr", "hr_manager", True)
    assert not sent                                            # off -> nothing sent
    c.put("/api/admin/settings", json={"email_mode": "redirect", "email_redirect_to": "qa@example.org"}, headers=H())
    r = runner.run("Run onboarding for EMP-1035", "hr.1", "hr_staff")
    runner.resume(r["request_id"], "mgr", "hr_manager", True)
    assert [m["to"] for m in sent] == [["qa@example.org"]]


def test_system_status(client, clerk):
    s = client.get("/api/admin/system", headers=H()).json()
    assert s["database"] == "sqlite" and s["employees"] == 36 and "clerk_admin_api" in s


def test_users_endpoint_reports_missing_clerk_secret(client, monkeypatch):
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
    assert client.get("/api/admin/users", headers=H()).status_code == 503
