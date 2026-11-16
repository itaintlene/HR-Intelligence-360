"""HTTP API: auth, role-scoped access, approvals. Uses dev-header auth (Clerk JWT path tested separately)."""
import jwt
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from hr360.api import auth
from hr360.api.main import app
from hr360.graph.runner import HRRunner


@pytest.fixture()
def client(ctx, monkeypatch):
    monkeypatch.setenv("HR360_AUTH_MODE", "dev")
    app.state.runner = HRRunner(ctx, MemorySaver())
    return TestClient(app)


def H(role, user="u1", emp=None, level=None):
    h = {"X-Dev-User": user, "X-Dev-Role": role}
    if emp:
        h["X-Dev-Employee"] = emp
    if level:
        h["X-Dev-Level"] = level
    return h


def test_requires_auth(client):
    assert client.get("/api/me").status_code == 401
    # least privilege: unknown / missing role -> employee (never elevated)
    me = client.get("/api/me", headers=H("hacker")).json()
    assert me["portal_role"] == "employee" and me["permissions"] == ["policy_query", "submit_standup", "view_own_work"]


def test_me_maps_portal_role_to_permissions(client):
    assert client.get("/api/me", headers=H("employee")).json()["permissions"] == ["policy_query", "submit_standup", "view_own_work"]
    assert "approve_actions" in client.get("/api/me", headers=H("hr", level="manager")).json()["permissions"]
    assert "approve_actions" not in client.get("/api/me", headers=H("hr")).json()["permissions"]
    pm = client.get("/api/me", headers=H("pm", emp="EMP-1002")).json()
    assert pm["role"] == "pm" and "view_team_leave" in pm["permissions"]


def test_employee_policy_question_and_forbidden_audit(client):
    r = client.post("/api/requests", data={"query": "How many sick days do I get?"}, headers=H("employee", emp="EMP-1010"))
    assert r.status_code == 200 and r.json()["state"]["policy_answer"]["citations"]
    assert "audit_findings" not in r.json()["state"]
    denied = client.post("/api/requests", data={"query": "Audit summary of all employees"}, headers=H("employee", emp="EMP-1010"))
    assert denied.json()["final_response"]["status"] == "denied"
    assert client.get("/api/employees", headers=H("employee")).status_code == 403
    up = client.post("/api/requests", data={"query": "audit"}, files=[("files", ("a.txt", b"x"))], headers=H("employee"))
    assert up.status_code == 403


def test_employee_cannot_see_other_users_requests(client):
    rid = client.post("/api/requests", data={"query": "How many sick days do I get?"}, headers=H("employee", emp="EMP-1010")).json()["request_id"]
    assert client.get(f"/api/requests/{rid}", headers=H("employee", emp="EMP-1010")).status_code == 200
    assert client.get(f"/api/requests/{rid}", headers=H("employee", emp="EMP-1011")).status_code == 404
    assert client.get(f"/api/requests/{rid}", headers=H("hr")).status_code == 200
    assert client.get("/api/requests", headers=H("employee", emp="EMP-1011")).json() == []


def test_pm_sees_only_direct_reports_leave(client, ctx):
    emp = ctx.db.employees()
    mgr = emp["manager_id"].dropna().iloc[0]
    team = set(emp[emp["manager_id"] == mgr]["employee_id"])
    r = client.post("/api/requests", data={"query": "Summarize pending leave requests"}, headers=H("pm", emp=mgr)).json()
    assert r["final_response"]["status"] == "completed"
    assert {x["employee_id"] for x in r["state"]["workflow_recommendations"]} <= team
    other = client.post("/api/requests", data={"query": "Summarize pending leave requests"}, headers=H("pm", emp="EMP-1030")).json()
    assert other["state"]["workflow_recommendations"] == []  # no direct reports
    assert client.post("/api/requests", data={"query": "Run onboarding for EMP-1031"}, headers=H("pm", emp=mgr)).json()["final_response"]["status"] == "denied"


def test_hr_document_audit_upload_and_report_download(client, sample_docs):
    with open(sample_docs["id_proof_EMP-1008_scan.png"], "rb") as fh:
        r = client.post("/api/requests", data={"query": "audit this document"}, files=[("files", ("../../evil name.png", fh.read()))],
                        headers=H("hr")).json()
    assert r["final_response"]["status"] == "completed" and r["state"]["audit_findings"]
    assert client.get(f"/api/requests/{r['request_id']}/report/pdf", headers=H("hr")).status_code == 200
    assert client.get(f"/api/requests/{r['request_id']}/report/pdf", headers=H("employee")).status_code == 404


def test_upload_rejects_bad_extension(client):
    r = client.post("/api/requests", data={"query": "audit"}, files=[("files", ("x.exe", b"MZ"))], headers=H("hr"))
    assert r.status_code == 400


def test_approval_flow_over_http(client):
    rid = client.post("/api/requests", data={"query": "Run onboarding for EMP-1035"}, headers=H("hr", "staff1")).json()["request_id"]
    pending = client.get("/api/approvals", headers=H("hr")).json()
    assert any(p["request_id"] == rid for p in pending)
    body = {"approved": True}
    assert client.post(f"/api/requests/{rid}/decision", json=body, headers=H("hr")).status_code == 403          # staff can't approve
    assert client.post(f"/api/requests/{rid}/decision", json=body, headers=H("pm", emp="EMP-1002")).status_code == 403
    ok = client.post(f"/api/requests/{rid}/decision", json=body, headers=H("hr", "mgr1", level="manager"))
    assert ok.status_code == 200 and ok.json()["state"]["approval_status"] == "approved"
    assert client.post(f"/api/requests/{rid}/decision", json=body, headers=H("hr", level="manager")).status_code == 409


def test_employee_directory_masking_by_role(client):
    staff = client.get("/api/employees", headers=H("hr")).json()
    mgr = client.get("/api/employees", headers=H("hr", level="manager")).json()
    assert not staff["full"] and "salary_band" not in staff["rows"][0] and "***" in staff["rows"][0]["email"]
    assert mgr["full"] and "salary_band" in mgr["rows"][0]


def test_audit_log_admin_only(client):
    assert client.get("/api/audit-log", headers=H("hr", level="manager")).status_code == 403
    assert client.get("/api/audit-log", headers=H("hr", level="admin")).status_code == 200


def test_clerk_jwt_verification(monkeypatch):
    """Sign a token with a throwaway RSA key and verify issuer/expiry/role-claim handling."""
    import time
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("HR360_AUTH_MODE", "clerk")
    monkeypatch.setenv("CLERK_ISSUER", "https://clerk.test")
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "http://localhost:5173")

    class FakeJWKS:
        def get_signing_key_from_jwt(self, _):
            return type("K", (), {"key": key.public_key()})()
    monkeypatch.setattr(auth, "_jwks", FakeJWKS())

    def tok(**over):
        c = {"sub": "user_1", "iss": "https://clerk.test", "iat": int(time.time()), "exp": int(time.time()) + 60,
             "azp": "http://localhost:5173", "metadata": {"role": "pm", "employee_id": "EMP-1002"}, **over}
        return jwt.encode(c, key, algorithm="RS256")

    p = auth.get_principal(authorization=f"Bearer {tok()}")
    assert (p.portal_role, p.internal_role, p.employee_id) == ("pm", "pm", "EMP-1002")
    from fastapi import HTTPException
    for bad in (tok(exp=int(time.time()) - 5), tok(iss="https://evil"), tok(azp="http://evil")):
        with pytest.raises(HTTPException):
            auth.get_principal(authorization=f"Bearer {bad}")
    for no_role in (tok(metadata={}), tok(metadata={"role": "root"}), tok(metadata="garbage")):
        assert auth.get_principal(authorization=f"Bearer {no_role}").internal_role == "employee"
    with pytest.raises(HTTPException):
        auth.get_principal(authorization=None)
