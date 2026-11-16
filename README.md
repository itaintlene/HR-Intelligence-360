# HR Intelligence 360

Multi-agent HR operations assistant built on **LangGraph**: policy Q&A (RAG), document intelligence (OCR + NLP),
deterministic compliance auditing, workflow automation, human-in-the-loop approval and full observability.
All data is **synthetic**.

## Quick start (Windows / PowerShell)

```powershell
py -3.13 -m venv .venv                       # Python 3.13 recommended (3.14 lacks some wheels)
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m spacy download en_core_web_sm      # optional, enables spaCy NER
.\.venv\Scripts\python scripts\seed.py       # synthetic DB + sample documents
.\.venv\Scripts\streamlit run hr360\ui\app.py
```

* **Tesseract OCR** must be installed for scanned documents (<https://github.com/UB-Mannheim/tesseract/wiki>); the
  default Windows path is auto-detected.
* **LLM is optional.** Without one, everything still works via deterministic fallbacks. To enable:
  `OPENAI_API_KEY` (+ optional `OPENAI_BASE_URL`, `HR360_LLM_MODEL`) for any OpenAI-compatible API, or
  `OLLAMA_MODEL=llama3.1` for Ollama. See `.env.example`.
* First run downloads the `all-MiniLM-L6-v2` embedding model; set `HR360_EMBEDDINGS=hash` to skip it (offline mode).

```powershell
.\.venv\Scripts\python -m pytest -q                  # 90+ tests (agents, graph e2e, evaluation gates, UI smoke)
.\.venv\Scripts\python -m hr360.evaluation           # routing / retrieval / audit / extraction metrics
.\.venv\Scripts\python scripts\export_graph.py       # regenerate docs/workflow_graph.{mmd,png}
```

## Web app (React + TanStack + Tailwind/shadcn + Clerk) - recommended UI

Three login types (Employee, Project Manager, HR) via Clerk; the FastAPI backend verifies the Clerk JWT and enforces RBAC.
Setup, role assignment and the permission matrix: **[docs/CLERK_SETUP.md](docs/CLERK_SETUP.md)**.

```powershell
.\.venv\Scripts\uvicorn hr360.api.main:app --port 8000          # API (needs CLERK_ISSUER, see docs)
cd web; copy .env.example .env.local; npm install; npm run dev   # UI  http://localhost:5173
```

## What to try in the (Streamlit) UI

| Role | Try | Shows |
|---|---|---|
| any | "How many days of earned leave can I carry forward?" | Workflow A, cited answer; "stock option vesting?" is refused |
| `hr_staff` | Upload files from `data/sample_docs/` + "Audit these documents" | Workflow B: OCR, field mismatch, expired ID, injection flagged, PDF/CSV report |
| `hr_staff` | "Run onboarding for EMP-1031, EMP-1035" | Workflow C → pauses for approval |
| `hr_manager` | Approvals tab → approve | Drafts queued to the (simulated) outbox |
| `hr_staff` | "Give me an audit summary of all employees" | Workflow D, dashboard, reports |
| `employee` | "Audit summary" | Denied by RBAC |

## Project layout

```
hr360/
  agents/      supervisor, policy_agent, document_agent, audit_agent, workflow_agent  (+ base.py DI container)
  graph/       state.py (HRGraphState + reducers) · builder.py (StateGraph) · nodes.py (guard/approval/report) · runner.py
  rules/       hr_rules.yaml (configurable rules) · engine.py (deterministic rules engine + finding validator)
  rag/         chunker · embeddings (sbert | hash fallback) · store (FAISS)
  llm/         provider.py (LangChain OpenAI/Ollama, optional) · prompts.py
  security/    rbac · sanitize (prompt-injection) · audit_log
  data/        db.py · synthetic.py (seeded anomalies = ground truth) · sample_docs.py
  reporting/   report.py (ReportLab PDF + CSV)
  ui/app.py    Streamlit dashboard         evaluation.py   metrics harness
data/policies/ sample HR policy documents   docs/ architecture + graph visualisation   tests/
```

## Agents (each testable on its own — see `tests/test_*_agent.py`)

| Agent | Tools | Guarantees |
|---|---|---|
| Supervisor | LLM/keyword classifier, fixed workflow table | Picks from a closed set of task types & plans; RBAC check; loop limit; does no domain work |
| HR Policy | embeddings + FAISS, citation formatter | Answers only from retrieved passages; `[S#]` citations and numbers validated; refuses when unsupported |
| Document Intelligence | PyMuPDF, python-docx, Tesseract, spaCy, Pydantic | Per-field confidence, missing/low-confidence flags, injection lines stripped, IDs masked, one bad file never kills a batch |
| HR Audit | pandas + YAML rules engine | Code decides compliance; `confirmed_violation` vs `potential_discrepancy`; evidence on every finding; LLM narrates only |
| HR Workflow | rule-driven templates | Prepares checklists/drafts/leave summaries; cannot send, approve or decide |

## Governance summary

RBAC (`employee < hr_staff < hr_manager < admin`) · approvals only by `hr_manager`/`admin` · audit log of every agent run,
denial and approval · synthetic data only · no hiring/firing/ranking/payroll automation (such requests route to
`unsupported`) · PII kept out of graph state and LLM prompts.

## Known limitations / next steps

* Authentication is simulated; replace with Clerk + FastAPI when moving to React.
* Email "sending" is a simulated outbox; leave decisions are summarised, never made.
* Rule/extraction patterns target the synthetic document formats; real documents need more templates or a layout model.
* The hash embedder is a fallback; accuracy numbers in `hr360.evaluation` were measured with both backends on a small labelled set.
