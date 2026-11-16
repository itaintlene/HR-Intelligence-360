# HR Intelligence 360 - full simulation report

*As-of 2026-11-16 - 60 employee profiles - 66 documents - 80 leave requests - embeddings: `auto` - LLM scenario: on*

## Result: 73/73 checks passed

| Scenario | Passed | Failed |
|---|---|---|
| 1 Policy Q&A (employees) | 4 | 0 |
| 2 Audit summary (HR staff) | 7 | 0 |
| 3 Document intelligence (HR staff, uploads) | 15 | 0 |
| 4 Onboarding + human approval | 19 | 0 |
| 5 Project-manager leave view | 5 | 0 |
| 6 RBAC matrix | 7 | 0 |
| 7 Admin console (Clerk faked) | 6 | 0 |
| 8 Adversarial / robustness | 7 | 0 |
| 9 Concurrency / load | 1 | 0 |
| 10 LLM routing & answers (sample) | 2 | 0 |

## Metrics

```json
{
  "policy": {
    "questions": 19,
    "right_source": "19/19",
    "fact_in_answer": "19/19",
    "citation_valid": "19/19",
    "out_of_scope_refused": "8/8"
  },
  "audit": {
    "profiles": 60,
    "expected": 36,
    "found": 36,
    "true_positive": 36,
    "recall": 1.0,
    "precision": 1.0
  },
  "documents": {
    "files": 66,
    "ocr_files": 15,
    "doc_type_accuracy": "63/63",
    "employee_id_accuracy": "63/63",
    "date_dept_field_accuracy": "42/42",
    "seconds_total": 12.6,
    "degraded_scans_readable": "3/3 (best effort, not scored)"
  },
  "leave": {
    "pending": 50,
    "flagged_for_review": 36
  },
  "load": {
    "requests": 80,
    "threads": 8,
    "errors": 0,
    "wall_s": 5.0,
    "p50_ms": 363,
    "p95_ms": 1170,
    "throughput_rps": 16.0
  },
  "llm_routing": {
    "cases": 10,
    "llm": "10/10",
    "keyword_fallback": "7/10"
  },
  "llm_policy_methods": {
    "llm": 1,
    "extractive": 7
  }
}
```

API latency (single calls, SQLite, local): p50 48 ms, p95 398 ms, max 9194 ms over 133 calls.

## Archetype mix (ground truth)

| Archetype | Profiles |
|---|---|
| clean | 24 |
| missing_docs_overdue | 6 |
| new_joiner_pending | 6 |
| dup_email | 4 |
| expired_id | 4 |
| expiring_id | 3 |
| missing_field | 3 |
| bad_probation | 2 |
| dangling_manager | 2 |
| invalid_value | 2 |
| offer_after_join | 2 |
| future_active | 2 |

## All checks

### 1 Policy Q&A (employees)

- PASS - answers cite the right policy document _(19/19)_
- PASS - answers contain the expected fact _(19/19; misses: [])_
- PASS - out-of-scope questions are refused (no hallucination) _(not refused: [])_
- PASS - prompt-injection queries neither escalate nor leak _([])_

### 2 Audit summary (HR staff)

- PASS - workflow completed
- PASS - every seeded problem is detected (recall = 100%) _(missing: [])_
- PASS - no unexplained findings (precision = 100%) _(unexplained: [])_
- PASS - confirmed vs potential classification matches archetype _([])_
- PASS - clean profiles are never flagged _([])_
- PASS - PDF + CSV report downloadable and complete _(pdf=200 csv_rows=36 findings=36)_
- PASS - per-employee audit is scoped to that employee _(12/12)_

### 3 Document intelligence (HR staff, uploads)

- PASS - batch 1 completed _(completed)_
- PASS - batch 2 completed _(completed)_
- PASS - batch 3 completed _(completed)_
- PASS - batch 4 completed _(completed)_
- PASS - batch 5 completed _(completed)_
- PASS - batch 6 completed _(completed)_
- PASS - batch 7 completed _(completed)_
- PASS - batch 8 completed _(completed)_
- PASS - batch 9 completed _(completed)_
- PASS - document type classified correctly _(63/63; [])_
- PASS - employee ID extracted correctly (PDF, DOCX and OCR scans) _(63/63)_
- PASS - dates / department extracted correctly _(42/42; [])_
- PASS - every expected document finding is raised (mismatch/expired/injection/unknown/no-id) _([])_
- PASS - no spurious document findings _([])_
- PASS - all prompt-injection documents flagged _(3 docs)_

### 4 Onboarding + human approval

- PASS - 12 onboarding targets across 3 batches
- PASS - admin sets email test-redirect mode
- PASS - batch EMP-2014.. pauses for approval _(status=awaiting_approval drafts=4)_
- PASS - batch EMP-2030.. pauses for approval _(status=awaiting_approval drafts=4)_
- PASS - batch EMP-2045.. pauses for approval _(status=awaiting_approval drafts=4)_
- PASS - drafting sent nothing
- PASS - approval queue lists all 3 requests
- PASS - HR staff cannot approve (403)
- PASS - PM cannot approve (403)
- PASS - employee cannot approve (403)
- PASS - still nothing sent after denied approvals
- PASS - manager approves batch 1
- PASS - batch 1: 4 emails sent (stubbed Resend, redirected) _(sent=4)_
- PASS - manager rejects batch 2 -> nothing sent
- PASS - admin partially approves batch 3 (1 sent, rest rejected) _(['sent', 'rejected', 'rejected', 'rejected'])_
- PASS - decision on finished request -> 409
- PASS - outbox records every released email with placeholder resolved _(rows=5)_
- PASS - email bodies mention the right missing documents
- PASS - audit log captures request, agents, approval

### 5 Project-manager leave view

- PASS - each PM sees exactly their direct reports' pending leave _(6/6)_
- PASS - HR sees all pending leave _(50/50)_
- PASS - no leave is approved by the system
- PASS - plain employee is denied the leave summary
- PASS - a non-manager 'PM' with no reports sees nothing

### 6 RBAC matrix

- PASS - 25 endpoint x persona permissions match the matrix _([])_
- PASS - unauthenticated requests are rejected (401) _([401, 401, 401, 401])_
- PASS - HR staff view masks PII & hides salary band; manager sees full
- PASS - employees can read only their own requests _(own=200 other=404)_
- PASS - employees cannot upload documents (403)
- PASS - role-escalation attempt via prompt is denied
- PASS - unknown role string degrades to employee, never elevates

### 7 Admin console (Clerk faked)

- PASS - admin lists all users; everyone starts with no role (=employee)
- PASS - admin assigns PM / HR staff / HR manager / HR admin / employee roles _([True, True, True, True, True])_
- PASS - invalid role changes rejected (missing PM id, unknown employee, bad role, self-demotion)
- PASS - non-admin cannot change roles
- PASS - every role change is audit-logged _(5)_
- PASS - admin settings persist

### 8 Adversarial / robustness

- PASS - SQL-injection-style text is harmless
- PASS - path-traversal filename is sanitised _(saved=['ata\\sim\\uploads\\ccdaadc76b\\evil_name.pdf'])_
- PASS - disallowed file type rejected (400)
- PASS - oversized upload rejected (413) _(413)_
- PASS - corrupt file does not abort the batch _(completed)_
- PASS - over-long query rejected (422) _(422)_
- PASS - forged / invalid JWT rejected (401) _(401)_

### 9 Concurrency / load

- PASS - 80 concurrent policy requests, zero errors _(0 errors: [])_

### 10 LLM routing & answers (sample)

- PASS - LLM routing at least as good as keyword fallback on paraphrased requests _(llm=10 rules=7)_
- PASS - LLM policy answers pass citation + number validation

## Notes

- Degraded (blurred) scans: 3/3 still produced the right employee ID via OCR.
