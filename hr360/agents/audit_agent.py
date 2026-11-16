"""Agent 4 - HR Audit Agent.

Compliance is decided ONLY by the deterministic RulesEngine. The LLM (optional) narrates the
already-decided findings; its output is stored separately and can never alter a finding.
"""
from __future__ import annotations

import logging
from collections import Counter

from hr360.agents.base import AgentContext
from hr360.llm import prompts
from hr360.models import Finding
from hr360.rules.engine import validate_findings

log = logging.getLogger("hr360.audit")


class HRAuditAgent:
    name = "audit"

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx

    # ---- tools ----
    def resolve_scope(self, task_type: str, employee_ids: list[str], extracted: list[dict]) -> list[str] | None:
        """None means "all employees"."""
        if task_type == "document_audit":
            return sorted({r["employee_id"] for r in extracted if r.get("employee_id")}) or employee_ids or None
        if employee_ids:
            return employee_ids
        if task_type == "onboarding":
            days = int(self.ctx.ruleset.settings.get("recent_joiner_days", 30))
            return self.ctx.db.recent_joiners(self.ctx.settings.as_of, days)
        return None

    def audit(self, scope: list[str] | None, extracted: list[dict] | None = None) -> tuple[list[Finding], list[str]]:
        db = self.ctx.db
        findings = self.ctx.engine.run(db.employees(), db.documents(), self.ctx.settings.as_of,
                                       extracted=extracted, scope=scope)
        return validate_findings(findings, self.ctx.ruleset)

    @staticmethod
    def summarize(findings: list[Finding], scope: list[str] | None) -> dict:
        return {
            "total_findings": len(findings),
            "by_severity": dict(Counter(f.severity for f in findings)),
            "by_classification": dict(Counter(f.classification for f in findings)),
            "by_rule": dict(Counter(f.rule_id for f in findings)),
            "employees_affected": len({f.employee_id for f in findings if f.employee_id}),
            "scope": "all employees" if scope is None else f"{len(scope)} employee(s)",
        }

    def explain(self, summary: dict, findings: list[Finding]) -> str:
        """LLM narrative with deterministic fallback. Sees IDs/rule codes only - no names or PII."""
        fallback = self._template_explanation(summary, findings)
        payload = {**summary, "top_findings": [f"{f.employee_id}: [{f.severity}/{f.classification}] {f.title}"
                                               for f in findings[:15]]}
        text = self.ctx.llm.invoke_text(prompts.AUDIT_EXPLAIN, str(payload))
        return text or fallback

    @staticmethod
    def _template_explanation(summary: dict, findings: list[Finding]) -> str:
        if not findings:
            return "The deterministic rules engine produced no findings for the audited scope."
        sev = summary["by_severity"]
        confirmed = summary["by_classification"].get("confirmed_violation", 0)
        potential = summary["by_classification"].get("potential_discrepancy", 0)
        top_rules = ", ".join(f"{r} ({n})" for r, n in Counter(f.rule_id for f in findings).most_common(3))
        return (f"The rules engine produced {summary['total_findings']} finding(s) across "
                f"{summary['employees_affected']} employee(s): {confirmed} confirmed violation(s) and "
                f"{potential} potential discrepancy(ies) needing verification. Severity mix: "
                f"{', '.join(f'{k}={v}' for k, v in sorted(sev.items()))}. Most frequent rules: {top_rules}. "
                "Address high-severity confirmed violations first, then verify potential discrepancies.")

    # ---- graph node ----
    def run(self, state: dict) -> dict:
        extracted = state.get("extracted_employee_data") or []
        scope = self.resolve_scope(state.get("task_type", ""), state.get("employee_ids") or [], extracted)
        findings, problems = self.audit(scope, extracted)
        summary = self.summarize(findings, scope)
        summary["narrative"] = self.explain(summary, findings)
        summary["validator_problems"] = problems
        out: dict = {"audit_findings": [f.model_dump() for f in findings], "audit_summary": summary}
        if scope is not None and not state.get("employee_ids"):
            out["employee_ids"] = scope
        return out
