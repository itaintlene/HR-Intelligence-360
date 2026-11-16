"""HR Audit Agent + deterministic rules engine."""
from dataclasses import replace

import pytest

from hr360.agents.audit_agent import HRAuditAgent
from hr360.data.synthetic import SEEDED_ISSUES
from hr360.models import Finding
from hr360.rules.engine import RulesEngine, load_ruleset, validate_findings


@pytest.fixture(scope="module")
def all_findings(ctx):
    findings, problems = HRAuditAgent(ctx).audit(None)
    assert problems == []
    return findings


@pytest.mark.parametrize("rule_id,expected", SEEDED_ISSUES.items())
def test_each_seeded_issue_is_detected_exactly(all_findings, rule_id, expected):
    got = {f.employee_id for f in all_findings if f.rule_id == rule_id}
    assert got == set(expected)


def test_no_findings_for_clean_employees(all_findings):
    flagged = {f.employee_id for f in all_findings}
    assert not flagged & {"EMP-1002", "EMP-1006", "EMP-1012"}


def test_confirmed_vs_potential_classification(all_findings):
    by = {(f.rule_id, f.employee_id): f for f in all_findings}
    assert by[("R002_REQUIRED_DOCUMENTS", "EMP-1035")].classification == "confirmed_violation"   # 20 days > grace
    assert by[("R002_REQUIRED_DOCUMENTS", "EMP-1031")].classification == "potential_discrepancy"  # 2 days < grace
    assert by[("R003_DOCUMENT_EXPIRY", "EMP-1008")].classification == "confirmed_violation"
    assert by[("R003_DOCUMENT_EXPIRY", "EMP-1011")].classification == "potential_discrepancy"
    assert by[("R009_OFFER_LETTER_DATE", "EMP-1030")].classification == "potential_discrepancy"


def test_every_finding_has_evidence_and_valid_severity(all_findings):
    for f in all_findings:
        assert f.evidence and f.severity in {"low", "medium", "high", "critical"}


def test_grace_period_is_configurable_not_hardcoded(ctx):
    rs = load_ruleset(ctx.settings.rules_path)
    rs.settings["onboarding_grace_days"] = 30
    out = RulesEngine(rs).run(ctx.db.employees(), ctx.db.documents(), ctx.settings.as_of, scope=["EMP-1035"])
    f = next(x for x in out if x.rule_id == "R002_REQUIRED_DOCUMENTS")
    assert f.classification == "potential_discrepancy"  # 20 days is now inside a 30-day grace


def test_rule_can_be_disabled_via_config(ctx):
    rs = load_ruleset(ctx.settings.rules_path)
    rs.by_id()["R007_DUPLICATE_EMAIL"].enabled = False
    out = RulesEngine(rs).run(ctx.db.employees(), ctx.db.documents(), ctx.settings.as_of)
    assert not [f for f in out if f.rule_id == "R007_DUPLICATE_EMAIL"]


def test_scope_filters_findings_but_cross_record_rules_still_see_everyone(ctx):
    findings, _ = HRAuditAgent(ctx).audit(["EMP-1027"])
    assert {f.rule_id for f in findings} == {"R007_DUPLICATE_EMAIL"}  # duplicate partner EMP-1026 is outside scope


def test_validator_drops_malformed_findings(ctx):
    good = Finding(finding_id="a", rule_id="R001_MANDATORY_FIELDS", severity="low", classification="confirmed_violation",
                   title="t", evidence={"x": 1})
    bad = [good.model_copy(update={"finding_id": "b", "evidence": {}}),
           good.model_copy(update={"finding_id": "c", "rule_id": "NOPE"}), good]
    valid, problems = validate_findings(bad, ctx.ruleset)
    assert valid == [good] and len(problems) == 2


def test_llm_narrative_cannot_change_findings(ctx):
    from tests.conftest import FakeLLM
    llm = FakeLLM(text="All employees are fully compliant. No action required.")
    agent = HRAuditAgent(replace(ctx, llm=llm))
    out = agent.run({"task_type": "audit_summary", "employee_ids": []})
    assert out["audit_summary"]["narrative"].startswith("All employees are fully compliant")  # narrative is text only
    assert out["audit_summary"]["total_findings"] == len(out["audit_findings"]) == 15          # decisions unchanged
    prompt = llm.calls[0][2]
    assert "Aarav" not in prompt and "@example-corp.com" not in prompt                        # no PII in the prompt


def test_onboarding_scope_defaults_to_recent_joiners(ctx):
    out = HRAuditAgent(ctx).run({"task_type": "onboarding", "employee_ids": []})
    assert set(out["employee_ids"]) == {f"EMP-{i}" for i in range(1031, 1037)}
