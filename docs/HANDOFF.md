# HR Intelligence 360 — Project Handoff

A prototype **HR assistant powered by AI agents**. It answers policy questions, checks HR records, automates onboarding, and tracks project work from daily stand-ups.

> All data is **synthetic** (made up). No real employee info is used.

| | |
|---|---|
| **Live app** | https://hr360-web-six.vercel.app |
| **Code** | https://github.com/itaintlene/HR-Intelligence-360 |
| **Demo logins** | Employee, Project Manager, HR (staff / manager / admin) — available on request |

---

## 1. The idea in 30 seconds

- **Employees** ask HR questions and post a short daily stand-up.
- **Project managers** see which projects are on track, who is blocked, and who has gone quiet.
- **HR** audits records, runs onboarding, and reviews each person's work **with proof**.
- **AI helps, people decide.** Nothing is sent or approved without a human. There are no scores and no rankings.

---

## 2. Who sees what

| | Employee | Project Manager | HR |
|---|:-:|:-:|:-:|
| Ask HR policy questions | ✅ | ✅ | ✅ |
| Daily stand-up + proof upload | ✅ | ✅ | – |
| See their own work record | ✅ | ✅ | – |
| Project progress and blockers | – | own projects | all |
| Pending leave summary | – | own team | all |
| Audits, onboarding, documents | – | – | ✅ |
| Approve emails | – | – | managers only |
| Admin page (`/admin`, hidden) | – | – | admins only |

Everyone starts as an **Employee**. An admin changes roles on the hidden `/admin` page.

---

## 3. Feature map — what is where

| Feature | Where to find it | Who |
|---|---|---|
| Choose a login | Home page | Everyone |
| Ask HR (answers with sources) | **Ask HR** | Everyone |
| Daily stand-up + proof | **Daily stand-up** | Employee, PM |
| My work record | **My work** | Employee, PM |
| Project health, blockers, milestones | **Projects** | PM, HR |
| Pending leave summary | **Team leave** / **Leave requests** | PM, HR |
| Compliance audit + PDF/CSV report | **Audit dashboard** | HR |
| Onboarding + email drafts | **Workflows** | HR |
| Approve or reject emails | **Approvals** | HR manager |
| Per-person work evidence | **Work records** | HR |
| Employee list (private data masked) | **Employees** | HR |
| Users, roles, email settings | `/admin` (not in the menu) | Admin |

---

## 4. Screenshots

### Home — three logins
![Home](handoff/img/01_landing.png)

### Employee

**Daily stand-up** — fill the form, then attach proof. AI summarises the file; a manager confirms it.
![Stand-up](handoff/img/02_employee_standup.png)

**My work** — the same record managers and HR see. Nothing hidden.
![My work](handoff/img/03_employee_my_work.png)

**Ask HR** — answers come only from company policy, with sources. Unknown questions are refused.
![Ask HR](handoff/img/04_employee_ask_hr.png)

### Project Manager

**Projects** — green / amber / red health, progress vs. where it should be.
![Projects](handoff/img/05_pm_projects.png)

**Project detail** — signals, blockers, milestones, team. People are listed A–Z, never ranked.
![Project detail](handoff/img/06_pm_project_detail.png)

**Team leave** — pending requests with policy flags. The system never approves leave.
![Team leave](handoff/img/07_pm_team_leave.png)

### HR

**Audit dashboard** — plain rules (not AI) find the problems. Every finding shows evidence.
![Audit](handoff/img/08_hr_audit_dashboard.png)

**Onboarding** — AI drafts reminder emails, then waits for a person.
![Onboarding](handoff/img/09_hr_onboarding_waiting.png)

**Approvals** — a manager reads each email and approves or rejects. Nothing is sent before this.
![Approvals](handoff/img/10_hr_approvals.png)

**Projects (HR view)** and a project with an open blocker:
![HR projects](handoff/img/11_hr_projects.png)
![Blocker](handoff/img/12_hr_project_blocker.png)

**Work records** — one person's stand-ups, GitHub activity and proof files, in one place.
![Work record](handoff/img/13_hr_work_record.png)

**Employees** — private fields are masked.
![Employees](handoff/img/14_hr_employees.png)

### Admin (hidden page)

![Admin settings](handoff/img/15_admin_settings.png)
![Admin system](handoff/img/16_admin_system.png)

---

## 5. 5-minute tour

1. Open the live app → **Employee login** → **Ask HR**: *"How many sick leave days do I get?"* Then ask something off-topic and see it refuse.
2. **Daily stand-up** → submit one, attach a text file as proof.
3. Sign in as **Project Manager** → **Projects** → open the *At risk* project.
4. Sign in as **HR** → **Audit dashboard** → **Run full audit**.
5. **Workflows** → *Run onboarding for EMP-1031, EMP-1032 and EMP-1035* → see it **wait for approval**.
6. Sign in as an **HR manager** → **Approvals** → read and approve.
7. **Work records** → open `EMP-1010`.

---

## 6. How it works

![Agent graph](handoff/img/17_agent_graph.png)

A **Supervisor** reads the request and sends it to specialist agents. It cannot invent new paths.

| Agent | Job |
|---|---|
| Policy | Searches HR policies and answers with sources |
| Document | Reads PDFs, Word files and scans; flags missing or odd data |
| Audit | Applies HR rules in code; AI only explains the result |
| Workflow | Builds checklists and email drafts; cannot send anything |
| Work Insights | Summarises project health and per-person evidence |

---

## 7. Built-in safety

- **Human approval** before any email goes out.
- **Rules decide compliance, not AI.** The AI only explains.
- **No scoring or ranking of people.** Asking for a "worst performer" is refused.
- **Role-based access** on every page and every API call.
- **Prompt-injection defence** on uploaded files.
- **Audit log** of every agent run, approval, and view of a person's record.
- **Private data kept out of AI prompts** and masked on screen.

---

## 8. Tech used

| Area | Tools |
|---|---|
| Agents | Python, LangGraph, LangChain |
| AI | Any OpenAI-compatible model (tested with Gemini); works without one |
| Search | Sentence Transformers + FAISS |
| Documents | PDF, Word, OCR, spaCy |
| Backend | FastAPI, SQLAlchemy |
| Database | SQLite (local), Postgres on Neon (live) |
| Frontend | React, TypeScript, TanStack Router + Query, Tailwind, shadcn-style UI |
| Login | Clerk |
| Email | Resend |
| Hosting | Vercel |
| Tracing | LangSmith |

---

## 9. Proof it works

- **153 automated tests** pass.
- **Full simulation:** 60 made-up employees, 66 documents, 87 checks, **all passing**. It plays five different users through every feature.
- Planted problems found: **36 of 36**, with no false alarms.
- Policy answers: right source and right fact in **19 of 19** questions; **8 of 8** off-topic questions refused.
- Report: [`SIMULATION_REPORT.md`](SIMULATION_REPORT.md)

---

## 10. Honest limits

This is a **prototype**.

- Synthetic data only.
- GitHub is **ready but not connected**. The import endpoint exists and is tested with made-up events.
- Email is in **test mode**. It sends only to one test address, after approval.
- Uploaded proof files are summarised but not stored permanently on the live host.
- Scanned-image reading is local-only for now. A vision AI model is the planned replacement.
- A free AI quota can slow answers; the app then falls back to simpler, still-checked answers.

**Next steps:** connect GitHub, permanent file storage, real HR data with a privacy review, email on a verified domain.

---

## 11. Run it yourself

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\pip install -r requirements-full.txt
copy .env.example .env             # add your own keys
.\.venv\Scripts\python scripts\seed.py
.\.venv\Scripts\python scripts\seed_work.py
.\.venv\Scripts\uvicorn hr360.api.main:app --port 8000
cd web; npm install; npm run dev   # http://localhost:5173
```

Run the tests: `pytest -q`  ·  Run the full simulation: `python -m hr360.simulation.run`

### Where things live

| Folder | What |
|---|---|
| `hr360/agents/` | The five agents + Supervisor |
| `hr360/work/` | Stand-ups, projects, analytics |
| `hr360/api/` | Backend API |
| `hr360/rules/hr_rules.yaml` | HR rules (editable, no code) |
| `web/src/pages/` | Screens |
| `tests/`, `hr360/simulation/` | Tests and simulation |
| `docs/` | This guide, architecture, Clerk setup |
