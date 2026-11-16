"""Agent-level evaluation harness.   Usage:  python -m hr360.evaluation [--json]

Measures, against labelled synthetic ground truth:
  * supervisor routing accuracy
  * policy retrieval hit-rate, citation validity, refusal precision on out-of-scope questions
  * deterministic audit precision / recall vs. the seeded anomalies
  * document extraction field accuracy on the generated sample documents
"""
from __future__ import annotations

import json
import sys

from hr360.agents.audit_agent import HRAuditAgent
from hr360.agents.base import AgentContext
from hr360.agents.document_agent import DocumentIntelligenceAgent
from hr360.agents.policy_agent import HRPolicyAgent
from hr360.agents.supervisor import SupervisorAgent
from hr360.data.synthetic import SEEDED_ISSUES

ROUTING_SET = [
    ("How many sick days do I get?", False, "policy_question"), ("What is the remote work policy?", False, "policy_question"),
    ("Can I carry forward leave?", False, "policy_question"), ("Audit these documents", True, "document_audit"),
    ("Please verify the attached files", True, "document_audit"), ("Run onboarding for EMP-1031", False, "onboarding"),
    ("Prepare onboarding for the new hires", False, "onboarding"), ("Give me an audit summary", False, "audit_summary"),
    ("Which employees have expired documents?", False, "audit_summary"), ("Summarize pending leave requests", False, "leave_summary"),
    ("Rank employees by performance", False, "unsupported"), ("Fire the bottom 10 percent", False, "unsupported"),
]
POLICY_SET = [  # (question, expected doc title, expected fact)
    ("How many days of earned leave can I carry forward?", "Leave Policy", "10"),
    ("How many sick leave days per year?", "Leave Policy", "10"),
    ("How many weeks of maternity leave?", "Leave Policy", "26"),
    ("What is the international daily meal allowance?", "Expense and Travel Policy", "60"),
    ("By when must expense claims be submitted?", "Expense and Travel Policy", "30"),
    ("Which documents must a new employee submit?", "Onboarding and Documentation Policy", "seven"),
    ("How long is the probation period?", "Onboarding and Documentation Policy", "90"),
    ("How many days per week in the office for hybrid work?", "Remote Work Policy", "3"),
    ("What is the gift value limit from vendors?", "Code of Conduct", "50"),
]
OUT_OF_SCOPE = ["What is the stock option vesting schedule?", "Who won the cricket world cup?", "Recommend a good restaurant",
                "What is the CEO's salary?"]
DOC_TRUTH = {  # file -> expected extracted fields
    "offer_letter_EMP-1033.pdf": {"document_type": "offer_letter", "employee_id": "EMP-1033"},
    "offer_letter_EMP-1034.docx": {"document_type": "offer_letter", "employee_id": "EMP-1034", "joining_date": "2026-11-11"},
    "id_proof_EMP-1008_scan.png": {"document_type": "id_proof", "employee_id": "EMP-1008", "expiry_date": "2026-10-27"},
    "id_proof_EMP-1011_scanned.pdf": {"document_type": "id_proof", "employee_id": "EMP-1011", "expiry_date": "2026-12-01"},
    "address_proof_EMP-1031_injection.pdf": {"document_type": "address_proof", "employee_id": "EMP-1031"},
    "bank_details_EMP-4040.pdf": {"document_type": "bank_details", "employee_id": "EMP-4040"},
}


def evaluate(ctx: AgentContext) -> dict:
    sup = SupervisorAgent(ctx)
    routing = sum(sup.classify_by_rules(q, f).task_type == t for q, f, t in ROUTING_SET) / len(ROUTING_SET)

    pol = HRPolicyAgent(ctx)
    hits = cites_ok = facts = 0
    for q, doc, fact in POLICY_SET:
        a = pol.run({"user_query": q})["policy_answer"]
        hits += (not a["refused"]) and any(c["doc_title"] == doc for c in a["citations"])
        cites_ok += (not a["refused"]) and a["validated"] and bool(a["citations"])
        facts += (not a["refused"]) and fact in a["answer"]
    refusals = sum(pol.run({"user_query": q})["policy_answer"]["refused"] for q in OUT_OF_SCOPE) / len(OUT_OF_SCOPE)

    findings, _ = HRAuditAgent(ctx).audit(None)
    got = {(f.rule_id, f.employee_id) for f in findings if f.rule_id in SEEDED_ISSUES}
    truth = {(r, e) for r, es in SEEDED_ISSUES.items() for e in es}
    tp = len(got & truth)

    doc_agent = DocumentIntelligenceAgent(ctx)
    ok = total = 0
    for fname, expected in DOC_TRUTH.items():
        path = ctx.settings.sample_docs_dir / fname
        if not path.exists():
            continue
        rec = doc_agent.process_file(path)[0].model_dump()
        for k, v in expected.items():
            total += 1
            ok += rec.get(k) == v
    return {
        "embedder": pol.store.embedder.name,
        "routing_accuracy": round(routing, 3),
        "policy": {"answer_hit_rate": round(hits / len(POLICY_SET), 3), "citation_validity": round(cites_ok / len(POLICY_SET), 3),
                   "fact_accuracy": round(facts / len(POLICY_SET), 3), "out_of_scope_refusal_rate": round(refusals, 3)},
        "audit": {"precision": round(tp / len(got), 3) if got else 0.0, "recall": round(tp / len(truth), 3)},
        "document_extraction_field_accuracy": round(ok / total, 3) if total else None,
    }


if __name__ == "__main__":
    c = AgentContext.build()
    result = evaluate(c)
    print(json.dumps(result, indent=2) if "--json" in sys.argv else "\n".join(f"{k}: {v}" for k, v in result.items()))
