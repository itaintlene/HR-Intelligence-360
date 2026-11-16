"""HR Workflow Agent: prepares, never executes."""
import pytest

from hr360.agents.audit_agent import HRAuditAgent
from hr360.agents.workflow_agent import HRWorkflowAgent


@pytest.fixture(scope="module")
def agent(ctx):
    return HRWorkflowAgent(ctx)


def onboarding_state(ctx):
    out = HRAuditAgent(ctx).run({"task_type": "onboarding", "employee_ids": ["EMP-1031", "EMP-1035"]})
    return {"task_type": "onboarding", "employee_ids": ["EMP-1031", "EMP-1035"], **out}


def test_drafts_require_approval_and_hold_no_pii(agent, ctx):
    drafts = agent.run(onboarding_state(ctx))["generated_email_drafts"]
    assert len(drafts) == 2 and all(d["requires_approval"] and d["status"] == "draft" for d in drafts)
    for d in drafts:
        assert "{first_name}" in d["body"] and "***@" in d["recipient_masked"]
        assert "Aarav" not in d["body"] and "@example-corp.com" not in d["body"]


def test_overdue_vs_pending_tone(agent, ctx):
    drafts = {d["employee_id"]: d for d in agent.run(onboarding_state(ctx))["generated_email_drafts"]}
    assert "overdue" in drafts["EMP-1035"]["body"] and "still outstanding" in drafts["EMP-1031"]["body"]
    assert "Tax declaration form" in drafts["EMP-1035"]["body"]


def test_checklist_reflects_documents_on_file(agent, ctx):
    recs = {r["employee_id"]: r for r in agent.run(onboarding_state(ctx))["workflow_recommendations"]
            if r["kind"] == "checklist"}
    status = {i["item"]: i["status"] for i in recs["EMP-1035"]["items"]}
    assert status["Tax declaration form submitted"] == "pending" and status["Offer letter signed and filed"] == "done"


def test_leave_summary_flags_but_never_approves(agent):
    out = agent.run({"task_type": "leave_summary"})
    recs = out["workflow_recommendations"]
    assert recs and all(r["requires_human_decision"] and r["kind"] == "leave_summary" for r in recs)
    assert not out["generated_email_drafts"]


def test_agent_never_writes_outbox(agent, ctx, settings):
    if settings.outbox_path.exists():
        settings.outbox_path.unlink()
    agent.run(onboarding_state(ctx))
    assert not settings.outbox_path.exists()


def test_task_recommendations_cover_findings(agent, ctx):
    findings = HRAuditAgent(ctx).run({"task_type": "audit_summary"})["audit_findings"]
    recs = agent.run({"task_type": "audit_summary", "audit_findings": findings})["workflow_recommendations"]
    assert recs and {r["priority"] for r in recs} <= {"low", "medium", "high"}
    assert all(r["kind"] == "task" for r in recs)
