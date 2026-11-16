"""Deterministic HR rules engine. NO LLM involvement: compliance is decided here, in code,
from configurable YAML rules. Rule *types* are code; rule *instances/thresholds* are config."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd
import yaml

from hr360.models import SEVERITY_ORDER, Finding

# --------------------------------------------------------------------------- config


@dataclass
class Rule:
    id: str
    type: str
    description: str = ""
    severity: str = "medium"
    enabled: bool = True
    params: dict = field(default_factory=dict)


@dataclass
class RuleSet:
    settings: dict
    rules: list[Rule]
    checklist: list[dict]
    vocab: dict = field(default_factory=dict)
    required_fields_by_doc_type: dict = field(default_factory=dict)

    def by_id(self) -> dict[str, Rule]:
        return {r.id: r for r in self.rules}


def load_ruleset(path: Path | str) -> RuleSet:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    rules = [Rule(id=r["id"], type=r["type"], description=r.get("description", ""),
                  severity=r.get("severity", "medium"), enabled=r.get("enabled", True),
                  params=r.get("params") or {}) for r in raw["rules"]]
    ids = [r.id for r in rules]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate rule ids in rules file")
    return RuleSet(settings=raw.get("settings", {}), rules=rules, checklist=raw.get("onboarding_checklist", []),
                   vocab=raw.get("vocab", {}),
                   required_fields_by_doc_type=raw.get("required_fields_by_doc_type", {}))


@dataclass
class RuleContext:
    employees: pd.DataFrame
    documents: pd.DataFrame
    as_of: date
    settings: dict
    extracted: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.employees = self.employees.copy()
        self.documents = self.documents.copy()
        self.employees["_join"] = pd.to_datetime(self.employees["joining_date"], errors="coerce")
        self.employees["_prob"] = pd.to_datetime(self.employees["probation_end"], errors="coerce")


# --------------------------------------------------------------------------- helpers
RULE_IMPLS: dict[str, Callable[[Rule, RuleContext], list[Finding]]] = {}


def rule_type(name: str):
    def deco(fn):
        RULE_IMPLS[name] = fn
        return fn
    return deco


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and not v.strip())


def _f(rule: Rule, emp: str | None, suffix: str, severity: str, cls: str, title: str,
       evidence: dict, rec: str) -> Finding:
    return Finding(finding_id=f"{rule.id}:{emp or 'NA'}:{suffix}", rule_id=rule.id, employee_id=emp,
                   severity=severity, classification=cls, title=title, evidence=evidence, recommendation=rec)


def _active(ctx: RuleContext) -> pd.DataFrame:
    e = ctx.employees
    return e[e["employment_status"].fillna("") != "Terminated"]


# --------------------------------------------------------------------------- rule types
@rule_type("mandatory_fields")
def _mandatory(rule, ctx):
    out = []
    for _, row in ctx.employees.iterrows():
        missing = [f for f in rule.params["fields"] if f in row and _blank(row[f])]
        if missing:
            out.append(_f(rule, row["employee_id"], "missing", rule.severity, "confirmed_violation",
                          f"Missing mandatory field(s): {', '.join(missing)}",
                          {"missing_fields": missing}, "Complete the employee master record."))
    return out


@rule_type("required_documents")
def _required_docs(rule, ctx):
    grace = int(ctx.settings.get("onboarding_grace_days", 7))
    required = rule.params["required"]
    have = ctx.documents.groupby("employee_id")["doc_type"].apply(set).to_dict()
    out = []
    for _, row in _active(ctx).iterrows():
        join = row["_join"]
        if pd.isna(join) or join.date() > ctx.as_of:
            continue  # not yet joined / unknown date (other rules cover it)
        missing = sorted(set(required) - have.get(row["employee_id"], set()))
        if not missing:
            continue
        days = (ctx.as_of - join.date()).days
        overdue = days > grace
        out.append(_f(rule, row["employee_id"], "docs",
                      rule.params["overdue_severity"] if overdue else rule.params["pending_severity"],
                      "confirmed_violation" if overdue else "potential_discrepancy",
                      f"{len(missing)} onboarding document(s) missing" + ("" if overdue else " (within grace period)"),
                      {"missing_documents": missing, "days_since_joining": days, "grace_days": grace},
                      "Request the missing documents from the employee." if overdue
                      else "Send a reminder before the grace period ends."))
    return out


@rule_type("document_expiry")
def _expiry(rule, ctx):
    warn = int(ctx.settings.get("expiry_warning_days", 30))
    docs = ctx.documents
    docs = docs[docs["doc_type"].isin(rule.params["applies_to"]) & docs["expiry_date"].notna()]
    out = []
    for _, d in docs.iterrows():
        exp = pd.to_datetime(d["expiry_date"], errors="coerce")
        if pd.isna(exp):
            continue
        exp = exp.date()
        ev = {"doc_type": d["doc_type"], "expiry_date": exp.isoformat()}
        if exp < ctx.as_of:
            out.append(_f(rule, d["employee_id"], d["doc_type"], rule.params["expired_severity"],
                          "confirmed_violation", f"{d['doc_type']} expired on {exp}",
                          {**ev, "days_overdue": (ctx.as_of - exp).days}, "Collect a renewed document."))
        elif exp <= ctx.as_of + timedelta(days=warn):
            out.append(_f(rule, d["employee_id"], d["doc_type"], rule.params["expiring_severity"],
                          "potential_discrepancy", f"{d['doc_type']} expires on {exp} (within {warn} days)",
                          {**ev, "days_remaining": (exp - ctx.as_of).days}, "Ask the employee to renew before expiry."))
    return out


@rule_type("date_order")
def _date_order(rule, ctx):
    a, b = rule.params["earlier"], rule.params["later"]
    out = []
    for _, row in ctx.employees.iterrows():
        da, db_ = pd.to_datetime(row[a], errors="coerce"), pd.to_datetime(row[b], errors="coerce")
        if pd.notna(da) and pd.notna(db_) and db_ < da:
            out.append(_f(rule, row["employee_id"], "order", rule.severity, "confirmed_violation",
                          f"{b} ({db_.date()}) is before {a} ({da.date()})",
                          {a: str(da.date()), b: str(db_.date())}, "Correct the date fields."))
    return out


@rule_type("future_joining_active")
def _future_active(rule, ctx):
    out = []
    for _, row in ctx.employees.iterrows():
        jd = row["_join"]
        if pd.notna(jd) and jd.date() > ctx.as_of and row["employment_status"] in rule.params["statuses"]:
            out.append(_f(rule, row["employee_id"], "future", rule.severity, "confirmed_violation",
                          f"Joining date {jd.date()} is in the future but status is {row['employment_status']}",
                          {"joining_date": str(jd.date()), "employment_status": row["employment_status"],
                           "as_of": ctx.as_of.isoformat()}, "Verify joining date or set status to 'Pre-joining'."))
    return out


@rule_type("reference_integrity")
def _reference(rule, ctx):
    fld = rule.params["field"]
    ids = set(ctx.employees["employee_id"])
    out = []
    for _, row in ctx.employees.iterrows():
        ref = row[fld]
        if _blank(ref):
            continue
        if ref == row["employee_id"]:
            out.append(_f(rule, row["employee_id"], "self", rule.severity, "confirmed_violation",
                          f"{fld} references the employee themself", {fld: ref}, "Assign a valid manager."))
        elif ref not in ids:
            out.append(_f(rule, row["employee_id"], "dangling", rule.severity, "confirmed_violation",
                          f"{fld} '{ref}' does not exist", {fld: ref}, "Assign a valid manager."))
    return out


@rule_type("duplicate")
def _duplicate(rule, ctx):
    fld = rule.params["field"]
    e = ctx.employees[ctx.employees[fld].notna()]
    dup = e[e.duplicated(fld, keep=False)]
    out = []
    for _, row in dup.iterrows():
        others = sorted(set(dup[dup[fld] == row[fld]]["employee_id"]) - {row["employee_id"]})
        out.append(_f(rule, row["employee_id"], "dup", rule.severity, "confirmed_violation",
                      f"Duplicate {fld} shared with {', '.join(others)}",
                      {"field": fld, "also_used_by": others}, f"Resolve the duplicate {fld}."))
    return out


@rule_type("valid_values")
def _valid_values(rule, ctx):
    out = []
    for fld, allowed in rule.params["checks"].items():
        for _, row in ctx.employees.iterrows():
            v = row.get(fld)
            if not _blank(v) and v not in allowed:
                out.append(_f(rule, row["employee_id"], fld, rule.severity, "confirmed_violation",
                              f"Invalid {fld}: '{v}'", {"field": fld, "value": v, "allowed": allowed},
                              f"Use one of: {', '.join(allowed)}."))
    return out


@rule_type("doc_after_joining")
def _doc_after_joining(rule, ctx):
    d = ctx.documents[ctx.documents["doc_type"] == rule.params["doc_type"]]
    emp = ctx.employees.set_index("employee_id")["_join"].to_dict()
    out = []
    for _, doc in d.iterrows():
        iss, jd = pd.to_datetime(doc["issue_date"], errors="coerce"), emp.get(doc["employee_id"])
        if pd.notna(iss) and jd is not None and pd.notna(jd) and iss > jd:
            out.append(_f(rule, doc["employee_id"], "late", rule.severity, "potential_discrepancy",
                          f"{rule.params['doc_type']} issued {iss.date()} after joining {jd.date()}",
                          {"issue_date": str(iss.date()), "joining_date": str(jd.date())},
                          "Confirm document dates with the employee."))
    return out


# ---- extracted-document rules (Workflow B) ----
def _rec_emp(rec: dict) -> str | None:
    return rec.get("employee_id")


@rule_type("extracted_unknown_employee")
def _x_unknown(rule, ctx):
    ids = set(ctx.employees["employee_id"])
    return [_f(rule, r["employee_id"], r["source_file"], rule.severity, "potential_discrepancy",
               "Document references an employee ID not in the HR database",
               {"source_file": r["source_file"]}, "Verify the employee ID on the document.")
            for r in ctx.extracted if r.get("employee_id") and r["employee_id"] not in ids]


@rule_type("extracted_mandatory")
def _x_mandatory(rule, ctx):
    out = []
    for r in ctx.extracted:
        missing = [f for f in rule.params["fields"] if _blank(r.get(f)) or r.get(f) == "unknown"]
        if missing:
            out.append(_f(rule, _rec_emp(r), r["source_file"], rule.severity, "potential_discrepancy",
                          f"Could not extract: {', '.join(missing)}",
                          {"source_file": r["source_file"], "missing_fields": missing},
                          "Review the document manually."))
    return out


@rule_type("extracted_mismatch")
def _x_mismatch(rule, ctx):
    emp = ctx.employees.set_index("employee_id")
    out = []
    for r in ctx.extracted:
        eid = _rec_emp(r)
        if not eid or eid not in emp.index:
            continue
        for fld in rule.params["fields"]:
            doc_v, db_v = r.get(fld), emp.at[eid, fld]
            if not _blank(doc_v) and not _blank(db_v) and str(doc_v).strip().lower() != str(db_v).strip().lower():
                out.append(_f(rule, eid, f"{r['source_file']}:{fld}", rule.severity, "potential_discrepancy",
                              f"{fld} on document differs from HR record",
                              {"source_file": r["source_file"], "field": fld, "document_value": doc_v,
                               "hr_record_value": db_v}, "Confirm which value is correct and update the record."))
    return out


@rule_type("extracted_low_confidence")
def _x_lowconf(rule, ctx):
    return [_f(rule, _rec_emp(r), r["source_file"], rule.severity, "potential_discrepancy",
               f"Low-confidence extraction: {', '.join(r['low_confidence_fields'])}",
               {"source_file": r["source_file"], "fields": r["low_confidence_fields"],
                "confidences": {k: r["field_confidence"].get(k) for k in r["low_confidence_fields"]}},
               "Manually verify these fields.")
            for r in ctx.extracted if r.get("low_confidence_fields")]


@rule_type("extracted_expired")
def _x_expired(rule, ctx):
    out = []
    for r in ctx.extracted:
        exp = pd.to_datetime(r.get("expiry_date"), errors="coerce")
        if pd.notna(exp) and exp.date() < ctx.as_of:
            out.append(_f(rule, _rec_emp(r), r["source_file"], rule.severity, "confirmed_violation",
                          f"Uploaded {r.get('document_type')} expired on {exp.date()}",
                          {"source_file": r["source_file"], "expiry_date": str(exp.date())},
                          "Request a valid replacement document."))
    return out


@rule_type("extracted_injection")
def _x_injection(rule, ctx):
    return [_f(rule, _rec_emp(r), r["source_file"], rule.severity, "confirmed_violation",
               "Document contains instruction-like text aimed at AI systems (stripped)",
               {"source_file": r["source_file"], "matches": r["injection_flags"][:5]},
               "Treat the document as untrusted; verify its provenance.")
            for r in ctx.extracted if r.get("injection_flags")]


# --------------------------------------------------------------------------- engine
class RulesEngine:
    def __init__(self, ruleset: RuleSet):
        self.ruleset = ruleset
        unknown = {r.type for r in ruleset.rules} - set(RULE_IMPLS)
        if unknown:
            raise ValueError(f"Unknown rule type(s): {unknown}")

    def run(self, employees: pd.DataFrame, documents: pd.DataFrame, as_of: date,
            extracted: list[dict] | None = None, scope: list[str] | None = None,
            only_extracted: bool = False) -> list[Finding]:
        """Run all enabled rules. Cross-record rules (duplicates, references) always see the full
        dataset; ``scope`` only filters which employees' findings are returned."""
        ctx = RuleContext(employees, documents, as_of, self.ruleset.settings, extracted or [])
        findings: list[Finding] = []
        for rule in self.ruleset.rules:
            if not rule.enabled:
                continue
            is_x = rule.type.startswith("extracted_")
            if (is_x and not extracted) or (only_extracted and not is_x):
                continue
            findings.extend(RULE_IMPLS[rule.type](rule, ctx))
        if scope:
            s = set(scope)
            findings = [f for f in findings if f.employee_id in s or (is_x_rule(f.rule_id) and f.employee_id is None)]
        return sorted(findings, key=lambda f: (-SEVERITY_ORDER[f.severity], f.employee_id or "", f.rule_id))


def is_x_rule(rule_id: str) -> bool:
    return rule_id.startswith("R1")


def validate_findings(findings: list[Finding], ruleset: RuleSet) -> tuple[list[Finding], list[str]]:
    """Audit-finding validator: drop malformed findings, de-duplicate, report problems."""
    known = ruleset.by_id()
    seen, valid, problems = set(), [], []
    for f in findings:
        if f.rule_id not in known:
            problems.append(f"{f.finding_id}: unknown rule")
        elif not f.evidence:
            problems.append(f"{f.finding_id}: no evidence")
        elif f.finding_id in seen:
            problems.append(f"{f.finding_id}: duplicate")
        else:
            seen.add(f.finding_id)
            valid.append(f)
    return valid, problems
