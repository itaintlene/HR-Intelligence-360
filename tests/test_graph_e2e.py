"""End-to-end LangGraph tests: Workflows A-D, human approval, checkpoint resume, limits, fallback."""
import json
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from hr360.agents.base import AgentContext
from hr360.graph.runner import HRRunner


def test_workflow_a_policy_question(runner):
    r = runner.run("How many days of earned leave can I carry forward?", "emp.1", "employee")
    fr = r["final_response"]
    assert r["status"] == "completed" and fr["task_type"] == "policy_question"
    assert fr["policy_answer"]["citations"] and "10" in fr["message"]
    assert set(r["state"]["agent_execution_status"]) == {"supervisor", "policy"}


def test_workflow_a_unsupported_policy_question_refused(runner):
    r = runner.run("What is the company's stock option vesting schedule?", "emp.1", "employee")
    assert r["final_response"]["policy_answer"]["refused"] is True


def test_workflow_b_document_audit(runner, sample_docs):
    files = [sample_docs[n] for n in ("offer_letter_EMP-1034.docx", "id_proof_EMP-1008_scan.png",
                                      "address_proof_EMP-1031_injection.pdf")]
    r = runner.run("Please audit these uploaded documents", "hr.1", "hr_staff", files)
    st, fr = r["state"], r["final_response"]
    assert fr["task_type"] == "document_audit" and fr["status"] == "completed"
    rules = {f["rule_id"] for f in st["audit_findings"]}
    assert {"R103_EXTRACTED_MISMATCH", "R105_EXTRACTED_EXPIRED", "R106_INJECTION_SUSPECTED"} <= rules
    assert Path(fr["report_paths"]["pdf"]).exists() and Path(fr["report_paths"]["csv"]).exists()
    assert set(st["employee_ids"]) == {"EMP-1034", "EMP-1008", "EMP-1031"}


def test_workflow_b_requires_permission(runner, sample_docs):
    r = runner.run("audit this document", "emp.1", "employee", [sample_docs["offer_letter_EMP-1033.pdf"]])
    assert r["final_response"]["status"] == "denied"
    assert not r["state"].get("audit_findings") and not r["state"].get("extracted_employee_data")


def test_workflow_c_onboarding_pauses_for_approval_then_queues(runner, settings):
    r = runner.run("Run onboarding for EMP-1031 and EMP-1035", "hr.1", "hr_staff")
    assert r["status"] == "awaiting_approval" and r["interrupt"]["type"] == "approval_request"
    drafts = r["interrupt"]["drafts"]
    assert {d["employee_id"] for d in drafts} == {"EMP-1031", "EMP-1035"}
    assert all(d["status"] == "draft" and d["requires_approval"] for d in drafts)
    assert not settings.outbox_path.exists(), "nothing may be sent before approval"
    # parallel stage + sequential stages all ran before the interrupt
    assert {"policy", "audit", "workflow", "report"} <= set(r["state"]["agent_execution_status"])

    done = runner.resume(r["request_id"], "mgr.1", "hr_manager", True, "ok")
    assert done["status"] == "completed" and done["state"]["approval_status"] == "approved"
    lines = [json.loads(l) for l in settings.outbox_path.read_text().splitlines()]
    assert len(lines) == 2 and all("{first_name}" not in l["body"] for l in lines)
    assert all(d["status"] == "queued" for d in done["state"]["generated_email_drafts"])


def test_approval_by_unauthorised_role_is_rejected(runner, settings):
    r = runner.run("onboarding for EMP-1035", "hr.1", "hr_staff")
    done = runner.resume(r["request_id"], "staff.2", "hr_staff", True)
    assert done["state"]["approval_status"] == "rejected_unauthorized"
    assert not settings.outbox_path.exists()


def test_approval_rejected(runner, settings):
    r = runner.run("onboarding for EMP-1035", "hr.1", "hr_staff")
    done = runner.resume(r["request_id"], "mgr.1", "hr_manager", False, "not now")
    assert done["state"]["approval_status"] == "rejected" and not settings.outbox_path.exists()


def test_checkpoint_survives_process_restart(ctx, settings, tmp_path):
    """Pause with one runner/connection, resume with a brand new one reading the same SQLite checkpoint."""
    import sqlite3
    path = tmp_path / "cp.db"
    r1 = HRRunner(ctx, SqliteSaver(sqlite3.connect(path, check_same_thread=False)))
    paused = r1.run("onboarding for EMP-1035", "hr.1", "hr_staff")
    assert paused["status"] == "awaiting_approval"
    r2 = HRRunner(ctx, SqliteSaver(sqlite3.connect(path, check_same_thread=False)))
    assert r2.get(paused["request_id"])["status"] == "awaiting_approval"
    done = r2.resume(paused["request_id"], "mgr.1", "hr_manager", False)
    assert done["status"] == "completed"


def test_workflow_d_audit_summary_with_reports(runner):
    r = runner.run("Give me an audit summary of all employee records", "hr.1", "hr_staff")
    st, fr = r["state"], r["final_response"]
    assert r["status"] == "completed" and fr["task_type"] == "audit_summary"
    assert fr["audit_summary"]["total_findings"] == len(st["audit_findings"]) > 10
    assert st["workflow_recommendations"] and not st.get("generated_email_drafts")
    assert Path(fr["report_paths"]["pdf"]).stat().st_size > 1000


def test_leave_summary_prepares_but_does_not_decide(runner):
    r = runner.run("Summarize pending leave requests", "hr.1", "hr_staff")
    recs = r["state"]["workflow_recommendations"]
    assert recs and all(x["requires_human_decision"] for x in recs)


def test_unsupported_request(runner):
    r = runner.run("Rank all employees and fire the bottom 10%", "hr.1", "hr_manager")
    assert r["final_response"]["status"] == "unsupported"
    assert set(r["state"]["agent_execution_status"]) == {"supervisor"}


def test_agent_failure_falls_back_to_partial_result(ctx, monkeypatch):
    from hr360.agents import audit_agent

    def boom(self, state):
        raise RuntimeError("db offline")
    monkeypatch.setattr(audit_agent.HRAuditAgent, "run", boom)
    from langgraph.checkpoint.memory import MemorySaver
    r = HRRunner(ctx, MemorySaver()).run("audit summary please", "hr.1", "hr_staff")
    fr = r["final_response"]
    assert fr["status"] == "partial" and any("audit" in e for e in fr["errors"])
    assert r["state"]["agent_execution_status"]["audit"]["attempts"] == 2  # retried once
    assert "workflow" not in r["state"]["agent_execution_status"]       # downstream stages skipped


def test_execution_limit_stops_runaway_plans(ctx):
    from dataclasses import replace
    from langgraph.checkpoint.memory import MemorySaver
    ctx2 = AgentContext(**{**ctx.__dict__, "settings": replace(ctx.settings, max_steps=2)})
    r = HRRunner(ctx2, MemorySaver()).run("audit summary of all employees", "hr.1", "hr_staff")
    assert any(e.startswith("execution_limit") for e in r["final_response"]["errors"])
    assert r["final_response"]["status"] == "partial"


def test_audit_log_records_agent_runs(runner, ctx):
    r = runner.run("How many sick leave days do I get?", "emp.9", "employee")
    actions = {(e["agent"], e["action"]) for e in ctx.audit_log.fetch(r["request_id"])}
    assert ("policy", "agent_run") in actions and ("supervisor", "request_completed") in actions


def test_workflow_c_with_uploads_runs_document_and_policy_agents_in_parallel(runner, sample_docs):
    r = runner.run("Onboarding for new joiner EMP-1033", "hr.1", "hr_staff", [sample_docs["offer_letter_EMP-1033.pdf"]])
    st = r["state"]
    assert {"document_intelligence", "policy"} <= set(st["agent_execution_status"])
    assert st["extracted_employee_data"][0]["employee_id"] == "EMP-1033" and st["retrieved_policy_chunks"]
    assert "EMP-1033" in st["employee_ids"]
