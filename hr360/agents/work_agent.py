"""Agent 6 - Work Insights Agent (project progress + contribution evidence).

* Numbers and flags come from hr360.work.analytics (deterministic). The LLM only narrates them.
* Never scores, ranks or recommends employment actions; the narrative prompt forbids it and requests for such output are
  routed to "unsupported" by the Supervisor.
* Scope is enforced here too: a PM only ever sees projects they manage.
* Proof-of-work files: text is extracted, injection lines stripped, then summarised by the LLM as UNTRUSTED data. The
  summary is labelled AI-generated and starts as review_status="pending" - a human verifies it.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from hr360.agents.base import AgentContext
from hr360.agents.document_agent import DocumentIntelligenceAgent
from hr360.llm import prompts
from hr360.security.sanitize import strip_injection, wrap_untrusted
from hr360.work import analytics
from hr360.work.repo import WorkRepo

log = logging.getLogger("hr360.work")
HR_ROLES = ("hr_staff", "hr_manager", "admin")
MAX_EVIDENCE_CHARS = 6000


class WorkInsightsAgent:
    name = "work_insights"

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx
        self.repo = WorkRepo(ctx.db.engine)
        self._docs: DocumentIntelligenceAgent | None = None

    # ------------------------------------------------------------------ scope
    def accessible_projects(self, role: str, user_id: str) -> list[str]:
        df = self.repo.projects()
        if role in HR_ROLES:
            return df["project_id"].tolist()
        if role == "pm":
            return df[df["manager_employee_id"] == user_id]["project_id"].tolist()
        return []

    # ------------------------------------------------------------------ narrative
    @staticmethod
    def _project_line(s: dict) -> str:
        p, pr = s["project"], s["progress"]
        quiet = [f["employee_id"] for f in s["flags"] if f["type"] == "quiet_member"]
        parts = [f"{p['name']} ({p['project_id']}): {pr['schedule_status'].replace('_', ' ')}"]
        if pr["pct_complete"] is not None:
            parts.append(f"{pr['pct_complete']}% of milestones done vs {pr['expected_pct']}% expected by timeline")
        if s["blockers"]:
            b = s["blockers"][0]
            parts.append(f"{len(s['blockers'])} open blocker(s), oldest {b['age_days']} days ({b['employee_id']})")
        if quiet:
            parts.append(f"no recent stand-up from {', '.join(quiet)}")
        carry = [f["employee_id"] for f in s["flags"] if f["type"] == "high_carryover"]
        if carry:
            parts.append(f"repeated unchanged plans from {', '.join(carry)}")
        return "; ".join(parts) + "."

    def _narrate(self, facts: str, template: str) -> str:
        text = self.ctx.llm.invoke_text(prompts.WORK_NARRATIVE, facts)
        return (text or template).strip()

    # ------------------------------------------------------------------ graph node
    def run(self, state: dict) -> dict:
        role, uid = state.get("user_role", "employee"), state.get("user_id", "")
        leaves = self.ctx.db.leave_requests()
        as_of: date = self.ctx.settings.as_of
        if state.get("task_type") == "person_record":
            ids = state.get("employee_ids") or []
            if not ids:
                return {"work_insights": {"kind": "person_record", "person": None,
                                          "narrative": "Please name the employee (for example EMP-1010) whose work record you want."}}
            rec = analytics.person_record(self.repo, leaves, ids[0], as_of)
            self.ctx.audit_log.record("view_person_record", request_id=state.get("request_id"), actor=uid, role=role, agent=self.name,
                                      detail={"employee_id": ids[0]})
            template = (f"Work record for {ids[0]} over the last {rec['window']['working_days']} working days: "
                        + "; ".join(f"{p['project']['name']}: {p['stats']['days_submitted']}/{p['stats']['days_expected']} stand-ups, "
                                    f"{p['github']['prs_merged']} PRs merged, {p['github']['commits']} commits, {p['evidence_count']} proof file(s) "
                                    f"({p['evidence_unreviewed']} awaiting human review)" for p in rec["projects"])
                        + (f". Signals for review: {', '.join(sorted({f['type'] for f in rec['flags']}))}." if rec["flags"] else ". No flags raised.")
                        + " " + analytics.DISCLAIMER)
            return {"work_insights": {"kind": "person_record", "person": rec, "narrative": self._narrate(
                f"Work record facts (JSON-like): {self._compact_person(rec)}", template)}}

        allowed = self.accessible_projects(role, uid)
        wanted = state.get("project_ids") or []
        denied = [p for p in wanted if p not in allowed]
        pids = [p for p in wanted if p in allowed] or ([] if wanted else allowed)
        projects = [analytics.project_status(self.repo, leaves, pid, as_of) for pid in pids[:12]]
        lines = [self._project_line(s) for s in projects]
        template = " ".join(lines) if lines else "No projects are available to you for this request."
        if denied:
            template += f" (You do not have access to: {', '.join(denied)}.)"
        narrative = self._narrate(f"Project status facts: {lines}. Flags: {[f for s in projects for f in s['flags']][:30]}", template) if projects else template
        return {"work_insights": {"kind": "project_status", "projects": projects, "narrative": narrative, "denied": denied}}

    @staticmethod
    def _compact_person(rec: dict) -> dict:
        return {"employee": rec["employee_id"], "window": rec["window"], "projects": [
            {"project": p["project"]["name"], "stats": {k: p["stats"][k] for k in ("days_submitted", "days_expected", "submission_rate", "carryover_rate")},
             "open_blocker": p["open_blocker"], "github": {k: p["github"][k] for k in ("commits", "prs_merged", "reviews", "events")},
             "evidence": p["evidence_count"], "evidence_unreviewed": p["evidence_unreviewed"]} for p in rec["projects"]],
            "flags": [{"type": f["type"], "message": f["message"]} for f in rec["flags"]]}

    # ------------------------------------------------------------------ proof-of-work analysis
    def analyze_evidence(self, path: str | Path, description: str = "") -> dict:
        """Read an uploaded proof file and produce an AI-generated, unverified summary."""
        if self._docs is None:
            self._docs = DocumentIntelligenceAgent(self.ctx)
        try:
            text, *_ = self._docs.load_text(Path(path))
        except Exception as exc:  # unsupported type, scanned PDF without OCR, corrupt file...
            return {"summary": f"The file could not be read automatically ({type(exc).__name__}); it is stored for human review.",
                    "method": "unreadable", "injection_flags": [], "chars": 0}
        clean, removed = strip_injection(text)
        clean = clean.strip()[:MAX_EVIDENCE_CHARS]
        if len(clean) < 20:
            return {"summary": "Little or no readable text was found in this file (it may be an image without text); a human should review it.",
                    "method": "extractive", "injection_flags": removed, "chars": len(clean)}
        user = f"{wrap_untrusted(clean, 'PROOF_FILE')}\n{wrap_untrusted(description[:500], 'EMPLOYEE_DESCRIPTION')}"
        llm = self.ctx.llm.invoke_text(prompts.EVIDENCE_SUMMARY, user)
        if llm:
            return {"summary": llm.strip()[:800], "method": "llm", "injection_flags": removed, "chars": len(clean)}
        lines = [ln.strip() for ln in clean.splitlines() if ln.strip()][:4]
        return {"summary": "Text excerpt: " + " | ".join(lines)[:400], "method": "extractive", "injection_flags": removed, "chars": len(clean)}
