"""Agent 5 - HR Workflow Agent.

PREPARES actions only: checklists, email DRAFTS, leave summaries, task recommendations.
It never sends email, approves leave, touches payroll or makes employment decisions - every
consequential item is flagged ``requires_approval`` / ``requires_human_decision`` and is released
only by the human-approval node.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta

import pandas as pd

from hr360.agents.base import AgentContext
from hr360.llm import prompts
from hr360.models import EmailDraft, WorkflowRecommendation
from hr360.security.rbac import mask_email

log = logging.getLogger("hr360.workflow")

DOC_LABEL = {"offer_letter": "Signed offer letter", "id_proof": "Government ID proof", "address_proof": "Address proof",
             "tax_form": "Tax declaration form", "nda": "Signed NDA", "bank_details": "Bank details",
             "education_certificate": "Education certificates"}


class HRWorkflowAgent:
    name = "workflow"

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx

    # ---- tools (all read-only / draft-only) ----
    def onboarding_checklist(self, employee_id: str, docs_df: pd.DataFrame) -> WorkflowRecommendation:
        have = set(docs_df[docs_df["employee_id"] == employee_id]["doc_type"])
        items = []
        for entry in self.ctx.ruleset.checklist:
            doc = entry.get("doc")
            status = ("done" if doc in have else "pending") if doc else "pending"
            items.append({"item": entry["item"], "status": status})
        pending = sum(1 for i in items if i["status"] == "pending")
        return WorkflowRecommendation(
            rec_id=f"CHK-{employee_id}", kind="checklist", employee_id=employee_id,
            title=f"Onboarding checklist for {employee_id} ({len(items) - pending}/{len(items)} done)",
            items=items, priority="high" if pending > 5 else "medium")

    def reminder_draft(self, employee_id: str, missing: list[str], overdue: bool) -> EmailDraft:
        grace = int(self.ctx.ruleset.settings.get("onboarding_grace_days", 7))
        _, email = self.ctx.db.employee_contact(employee_id)
        bullets = "\n".join(f"  - {DOC_LABEL.get(m, m)}" for m in missing)
        tone = ("are now overdue" if overdue else "are still outstanding")
        body = (f"Hi {{first_name}},\n\nThank you for joining us! Our records show the following onboarding "
                f"documents {tone}:\n\n{bullets}\n\nPer the Onboarding and Documentation Policy (section 3), all "
                f"mandatory documents are due within {grace} calendar days of the joining date. Please upload them "
                f"to the HR portal at your earliest convenience, or reply if you need help.\n\nThanks,\nHR Operations")
        return EmailDraft(draft_id=f"DRAFT-{employee_id}-docs", employee_id=employee_id,
                          recipient_masked=mask_email(email), subject=f"Action needed: {len(missing)} onboarding document(s) pending",
                          body=body)

    def leave_recommendations(self) -> list[WorkflowRecommendation]:
        leaves = self.ctx.db.leave_requests()
        emps = self.ctx.db.employees().set_index("employee_id")["department"].to_dict()
        if leaves.empty:
            return []
        leaves = leaves.assign(_s=pd.to_datetime(leaves["start_date"]), _e=pd.to_datetime(leaves["end_date"]),
                               dept=leaves["employee_id"].map(emps))
        max_casual = int(self.ctx.ruleset.settings.get("casual_leave_max_consecutive_days", 3))
        recs = []
        for _, lv in leaves[leaves["status"] == "Pending"].iterrows():
            overlap = leaves[(leaves["dept"] == lv["dept"]) & (leaves["leave_id"] != lv["leave_id"])
                             & (leaves["_s"] <= lv["_e"]) & (leaves["_e"] >= lv["_s"])]
            flags = []
            if lv["leave_type"] == "Casual" and lv["days"] > max_casual:
                flags.append(f"Casual leave of {lv['days']:.0f} days exceeds the {max_casual}-day limit (Leave Policy section 3)")
            if len(overlap):
                flags.append(f"{len(overlap)} other leave(s) overlap in the same department")
            recs.append(WorkflowRecommendation(
                rec_id=f"LEAVE-{lv['leave_id']}", kind="leave_summary", employee_id=lv["employee_id"],
                title=f"{lv['leave_type']} leave {lv['start_date']} to {lv['end_date']} ({lv['days']:.0f} day(s))",
                detail="; ".join(flags) or "No policy flags detected.",
                items=[{"leave_id": lv["leave_id"], "submitted_on": lv["submitted_on"], "flags": flags}],
                priority="medium" if flags else "low", requires_human_decision=True))
        return recs

    def task_recommendations(self, findings: list[dict]) -> list[WorkflowRecommendation]:
        due = self.ctx.ruleset.settings.get("task_due_days", {})
        recs, seen = [], set()
        for f in findings:
            key = (f["employee_id"], f["rule_id"])
            if key in seen:
                continue
            seen.add(key)
            days = int(due.get(f["severity"], 7))
            recs.append(WorkflowRecommendation(
                rec_id=f"TASK-{f['employee_id']}-{f['rule_id']}", kind="task", employee_id=f["employee_id"],
                title=f["title"], detail=f"{f['recommendation']} (suggested due {self.ctx.settings.as_of + timedelta(days=days)})",
                priority="high" if f["severity"] in ("high", "critical") else ("medium" if f["severity"] == "medium" else "low"),
                requires_human_decision=f["classification"] == "potential_discrepancy"))
        return recs

    def summarize(self, state: dict, recs: list[WorkflowRecommendation], drafts: list[EmailDraft]) -> str:
        audit = state.get("audit_summary") or {}
        facts = {"task_type": state.get("task_type"), "recommendations_by_kind": dict(Counter(r.kind for r in recs)),
                 "email_drafts_pending_approval": len(drafts), "audit_total_findings": audit.get("total_findings"),
                 "audit_by_severity": audit.get("by_severity"), "audit_by_classification": audit.get("by_classification"),
                 "high_priority_items": sum(1 for r in recs if r.priority == "high")}
        text = self.ctx.llm.invoke_text(prompts.WORKFLOW_SUMMARY, str(facts))
        if text:
            return text
        parts = [f"Prepared {len(recs)} recommendation(s)"]
        if drafts:
            parts.append(f"{len(drafts)} email draft(s) awaiting human approval (nothing has been sent)")
        if audit.get("total_findings") is not None:
            parts.append(f"audit produced {audit['total_findings']} finding(s)")
        leave = sum(1 for r in recs if r.kind == "leave_summary")
        if leave:
            parts.append(f"{leave} pending leave request(s) summarised for manager decision (none approved by this system)")
        return "; ".join(parts) + "."

    # ---- graph node ----
    def run(self, state: dict) -> dict:
        task = state.get("task_type")
        findings = state.get("audit_findings") or []
        recs: list[WorkflowRecommendation] = []
        drafts: list[EmailDraft] = []
        if task == "onboarding":
            docs = self.ctx.db.documents()
            for eid in state.get("employee_ids") or []:
                recs.append(self.onboarding_checklist(eid, docs))
            for f in findings:
                if f["rule_id"] == "R002_REQUIRED_DOCUMENTS" and f["employee_id"]:
                    drafts.append(self.reminder_draft(f["employee_id"], f["evidence"]["missing_documents"],
                                                      f["classification"] == "confirmed_violation"))
            recs.extend(self.task_recommendations([f for f in findings if f["rule_id"] != "R002_REQUIRED_DOCUMENTS"]))
        elif task == "audit_summary":
            recs.extend(self.task_recommendations(findings))
        elif task == "leave_summary":
            recs.extend(self.leave_recommendations())
        return {"workflow_recommendations": [r.model_dump() for r in recs],
                "generated_email_drafts": [d.model_dump() for d in drafts],
                "workflow_summary": self.summarize(state, recs, drafts)}
