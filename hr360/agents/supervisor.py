"""Agent 1 - Supervisor / Orchestrator.

Responsibilities: classify the request, authorise it (RBAC), pick one of a FIXED set of workflows,
step through its stages, and compose the final response. It never extracts documents, audits
records or retrieves policy itself - it only routes to the specialised agents.

Controlled routing: the LLM (or keyword fallback) may only choose a ``task_type`` from a closed
enum; the execution plan for each task type is a hard-coded workflow table, never LLM-generated.
"""
from __future__ import annotations

import logging
import re
from typing import get_args

from hr360.agents.base import AgentContext
from hr360.llm import prompts
from hr360.models import TaskClassification, TaskType
from hr360.security.rbac import authorize_task
from hr360.security.sanitize import wrap_untrusted

log = logging.getLogger("hr360.supervisor")

AGENT_NODES = ("document_intelligence", "policy", "audit", "workflow", "report", "approval", "work_insights")
ONBOARDING_POLICY_QUERY = "What documents must a new employee submit during onboarding and what is the deadline?"

# predefined workflows (A-D plus leave/pending-task summary). Inner lists run in PARALLEL.
WORKFLOWS: dict[str, list[list[str]]] = {
    "policy_question": [["policy"]],                                                         # A
    "document_audit": [["document_intelligence"], ["audit"], ["report"]],                    # B
    "onboarding": [["document_intelligence", "policy"], ["audit"], ["workflow"], ["report"], ["approval"]],  # C
    "audit_summary": [["audit"], ["workflow"], ["report"]],                                  # D
    "leave_summary": [["workflow"]],
    "project_status": [["work_insights"]],
    "person_record": [["work_insights"]],
    "unsupported": [],
}
EMP_ID_RX = re.compile(r"\bEMP[-\s_]?(\d{3,6})\b", re.IGNORECASE)

_FORBIDDEN = re.compile(r"\b(fire|terminate|hire|rank|payroll|salary|promot\w+|reject candidate|worst|best performer|top performer|"
                        r"bottom \d+|leaderboard|rate (the |all |my )?(employees|people|team)|performance (score|rating|ranking))\b", re.IGNORECASE)
_RANKING = re.compile(r"\b(worst|best performer|top performer|bottom \d+|leaderboard|rate (the |all |my )?(employees|people|team)|"
                     r"performance (score|rating|ranking)|rank(ing)? (the |all |my )?(employees|people|team|staff))\b", re.IGNORECASE)
PROJ_ID_RX = re.compile(r"\bPRJ[-\s_]?(\d{2,5})\b", re.IGNORECASE)


class SupervisorAgent:
    name = "supervisor"

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx

    # ---------------------------------------------------------------- classification
    @staticmethod
    def extract_employee_ids(text: str) -> list[str]:
        seen: list[str] = []
        for m in EMP_ID_RX.finditer(text or ""):
            eid = f"EMP-{m.group(1)}"
            if eid not in seen:
                seen.append(eid)
        return seen

    @staticmethod
    def extract_project_ids(text: str) -> list[str]:
        seen: list[str] = []
        for m in PROJ_ID_RX.finditer(text or ""):
            pid = f"PRJ-{m.group(1)}"
            if pid not in seen:
                seen.append(pid)
        return seen

    @staticmethod
    def classify_by_rules(query: str, has_files: bool) -> TaskClassification:
        q = query.lower()
        if _RANKING.search(q):
            return TaskClassification(task_type="unsupported", rationale="ranking / scoring employees is not supported")
        if _FORBIDDEN.search(q) and not re.search(r"polic|leave|how|what", q):
            return TaskClassification(task_type="unsupported", rationale="consequential employment decision")
        if any(k in q for k in ("onboard", "new joiner", "new hire", "new employee", "checklist", "welcome")) and \
                not q.rstrip().endswith("?"):
            return TaskClassification(task_type="onboarding", rationale="onboarding keywords")
        if any(k in q for k in ("work record", "contribution", "activity of", "daily updates of", "work history", "evidence for", "stand-up history"))                 and EMP_ID_RX.search(q):
            return TaskClassification(task_type="person_record", rationale="employee work-record keywords")
        if any(k in q for k in ("project status", "project progress", "status of project", "blocker", "running slow", "behind schedule", "stand-up",
                                "standup", "stand up", "how is project", "project health")) or PROJ_ID_RX.search(q):
            return TaskClassification(task_type="project_status", rationale="project / stand-up keywords")
        if any(k in q for k in ("pending leave", "leave request", "leave summary", "pending task", "leave applications")):
            return TaskClassification(task_type="leave_summary", rationale="leave/task keywords")
        if has_files:
            return TaskClassification(task_type="document_audit", rationale="documents uploaded")
        if any(k in q for k in ("audit", "compliance", "non-compliant", "discrepanc", "violation", "missing documents",
                                "expired", "inconsistent")):
            return TaskClassification(task_type="audit_summary", rationale="audit keywords")
        if "?" in q or any(k in q for k in ("policy", "how many", "can i", "what is", "how do", "entitle", "allowance", "eligible")):
            return TaskClassification(task_type="policy_question", rationale="question / policy keywords")
        return TaskClassification(task_type="unsupported", rationale="no matching workflow")

    def classify(self, query: str, has_files: bool) -> TaskClassification:
        llm_out = self.ctx.llm.invoke_structured(
            TaskClassification, prompts.SUPERVISOR_CLASSIFY,
            f"{wrap_untrusted(query, 'REQUEST')}\nDocuments uploaded: {has_files}")
        if llm_out is not None and llm_out.task_type in get_args(TaskType):
            if llm_out.task_type == "document_audit" and not has_files:
                log.info("LLM chose document_audit without files; using rules")
            else:
                return llm_out
        return self.classify_by_rules(query, has_files)

    def build_plan(self, task: str, has_files: bool) -> list[list[str]]:
        plan = [list(stage) for stage in WORKFLOWS[task]]
        if task == "onboarding" and not has_files:
            plan[0] = ["policy"]  # nothing to extract
        return plan

    # ---------------------------------------------------------------- graph nodes
    def plan_node(self, state: dict) -> dict:
        query = state.get("user_query", "")
        files = state.get("uploaded_files") or []
        cls = self.classify(query, bool(files))
        task = cls.task_type
        ids = self.extract_employee_ids(query)
        out: dict = {"task_type": task, "task_rationale": cls.rationale, "employee_ids": ids,
                     "project_ids": self.extract_project_ids(query), "stage_idx": 0, "step_count": 0, "current_stage": [], "approval_status": "not_required",
                     "agent_execution_status": {"supervisor": {"status": "completed", "task_type": task}}}
        allowed, why = authorize_task(state.get("user_role", "employee"), task)
        if not allowed:
            out.update(task_type="unsupported", plan=[], errors=[f"access_denied: {why}"],
                       task_rationale="access denied")
            self.ctx.audit_log.record("access_denied", request_id=state.get("request_id"), actor=state.get("user_id"),
                                      role=state.get("user_role"), agent="supervisor", detail=why)
            out["agent_execution_status"] = {"supervisor": {"status": "denied", "task_type": task}}
            return out
        if task == "policy_question":
            out["policy_query"] = query
        elif task == "onboarding":
            out["policy_query"] = ONBOARDING_POLICY_QUERY
        out["plan"] = self.build_plan(task, bool(files))
        return out

    def dispatch_node(self, state: dict) -> dict:
        """Hub node: advance to the next stage of the fixed plan, enforcing execution limits."""
        step = state.get("step_count", 0) + 1
        idx = state.get("stage_idx", 0)
        plan = state.get("plan") or []
        failed = [a for a, s in (state.get("agent_execution_status") or {}).items() if s.get("status") == "failed"]
        if step > self.ctx.settings.max_steps:
            return {"current_stage": [], "step_count": step, "errors": ["execution_limit: max supervisor steps exceeded"]}
        if failed or idx >= len(plan):
            return {"current_stage": [], "step_count": step}
        stage = [n for n in plan[idx] if n in AGENT_NODES]  # whitelist: no arbitrary nodes
        return {"current_stage": stage, "stage_idx": idx + 1, "step_count": step}

    @staticmethod
    def route(state: dict) -> list[str] | str:
        stage = state.get("current_stage") or []
        return stage if stage else "finalize"

    def finalize_node(self, state: dict) -> dict:
        task = state.get("task_type", "unsupported")
        errors = state.get("errors") or []
        statuses = state.get("agent_execution_status") or {}
        failed = [a for a, s in statuses.items() if s.get("status") == "failed"]
        denied = any(e.startswith("access_denied") for e in errors)
        if denied:
            status, message = "denied", errors[0].split(": ", 1)[1]
        elif task == "unsupported":
            status = "unsupported"
            message = ("This request is outside what the assistant can do (policy Q&A, document audit, onboarding "
                       "automation, audit summaries, leave summaries). It does not make hiring, firing, ranking or "
                       "payroll decisions.")
        elif failed or any(e.startswith("execution_limit") for e in errors):
            status, message = "partial", f"Completed with problems in: {', '.join(failed) or 'execution limit'}."
        elif state.get("approval_status") == "rejected":
            status, message = "completed", "Workflow completed; the proposed actions were rejected by the approver."
        else:
            status, message = "completed", ""

        resp: dict = {"request_id": state.get("request_id"), "task_type": task, "status": status,
                      "approval_status": state.get("approval_status"), "errors": errors}
        if task == "policy_question" and state.get("policy_answer"):
            pa = state["policy_answer"]
            message = pa["answer"]
            resp["policy_answer"] = pa
        if state.get("extracted_employee_data"):
            resp["documents_processed"] = len(state["extracted_employee_data"])
        if state.get("audit_summary"):
            resp["audit_summary"] = state["audit_summary"]
            resp["findings_count"] = len(state.get("audit_findings") or [])
            message = message or state["audit_summary"].get("narrative", "")
        if state.get("workflow_summary"):
            resp["workflow_summary"] = state["workflow_summary"]
            if not message or task in ("leave_summary",):
                message = state["workflow_summary"]
        if state.get("work_insights"):
            wi = state["work_insights"]
            resp["work_insights"] = {"kind": wi["kind"], "narrative": wi.get("narrative")}
            message = message or wi.get("narrative", "")
        resp["recommendations_count"] = len(state.get("workflow_recommendations") or [])
        resp["email_drafts_count"] = len(state.get("generated_email_drafts") or [])
        if state.get("report_paths"):
            resp["report_paths"] = state["report_paths"]
        resp["message"] = message
        self.ctx.audit_log.record("request_completed", request_id=state.get("request_id"), actor=state.get("user_id"),
                                  role=state.get("user_role"), agent="supervisor",
                                  detail={"task_type": task, "status": status})
        return {"final_response": resp}
