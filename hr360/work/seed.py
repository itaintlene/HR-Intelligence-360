"""Synthetic projects / stand-ups / GitHub activity with ground truth for tests, the simulation and the demo."""
from __future__ import annotations

import random
from datetime import date, timedelta

from hr360.work.analytics import working_days
from hr360.work.repo import WorkRepo

# project -> (name, health, member archetypes in order; remaining members are "consistent")
PLAN = {
    "PRJ-101": ("Customer Portal", "on_track", ["consistent"] * 5),
    "PRJ-102": ("Payments Gateway", "on_track", ["consistent", "consistent", "quiet", "consistent", "consistent"]),
    "PRJ-103": ("Data Platform Migration", "behind", ["consistent", "blocker", "consistent", "consistent", "consistent"]),
    "PRJ-104": ("Mobile App v2", "at_risk", ["consistent", "carryover", "consistent", "consistent", "consistent"]),
    "PRJ-105": ("Internal Analytics", "on_track", ["consistent", "sporadic", "no_github", "consistent", "consistent"]),
    "PRJ-106": ("Legacy Decommission", "done", ["consistent"] * 4),
}
FLAG_FOR = {"quiet": "quiet_member", "blocker": "stale_blocker", "carryover": "high_carryover", "no_github": "activity_mismatch"}
VERBS = ["Implemented", "Refactored", "Debugged", "Reviewed", "Tested", "Documented", "Optimised", "Designed", "Deployed", "Investigated"]
THINGS = ["login flow", "invoice export", "search index", "cache layer", "notification service", "audit trail", "report builder", "API gateway",
          "retry logic", "schema migration", "dashboard widgets", "rate limiter", "payment webhook", "onboarding wizard", "data validators"]


def _text(rng: random.Random) -> str:
    return f"{rng.choice(VERBS)} {rng.choice(THINGS)} (ticket {rng.randint(1000, 9999)}) and {rng.choice(VERBS).lower()} {rng.choice(THINGS)}"


def seed_work(repo: WorkRepo, employee_ids: list[str], lead_ids: list[str], as_of: date, seed: int = 11) -> dict:
    rng = random.Random(seed)
    days = working_days(as_of, 20)
    pool = [e for e in employee_ids if e not in lead_ids] or list(employee_ids)
    manifest = {"flags": [], "schedule": {}, "members": {}}
    cursor = 0
    for n, (pid, (name, health, archs)) in enumerate(PLAN.items()):
        lead = lead_ids[n % len(lead_ids)]
        members = [pool[(cursor + i) % len(pool)] for i in range(len(archs))]
        cursor += len(archs)
        slug = name.lower().replace(" ", "-")
        start = as_of - timedelta(days=60)
        target = as_of + timedelta(days=40)
        if health == "done":
            target = as_of - timedelta(days=5)
        statuses = {"on_track": ["done"] * 3 + ["todo"] * 2, "at_risk": ["done", "done", "todo", "done", "todo"],
                    "behind": ["done", "done", "todo", "todo", "todo"], "done": ["done"] * 5}[health]
        ms = []
        for k, st in enumerate(statuses):
            due = start + timedelta(days=12 * (k + 1))                              # 12, 24, 36, 48, 60 days after start
            if st == "todo" and k == 2 and health in ("at_risk", "behind"):
                due = as_of - timedelta(days=4)                                      # one overdue milestone
            elif st == "todo" and due <= as_of:
                due = as_of + timedelta(days=10 + k * 7)
            ms.append({"name": f"Milestone {k + 1}", "due_date": due.isoformat(), "status": st, "done_on": due.isoformat() if st == "done" else None, "weight": 1.0})
        repo.create_project({"project_id": pid, "name": name, "description": f"{name} (synthetic)", "manager_employee_id": lead, "start_date": start.isoformat(),
                             "target_date": target.isoformat(), "status": "done" if health == "done" else "active", "repo": f"sim-corp/{slug}"},
                            [{"employee_id": m, "role_on_project": "contributor"} for m in members], ms)
        manifest["schedule"][pid] = health
        manifest["members"][pid] = dict(zip(members, archs))
        events = []
        for emp, arch in zip(members, archs):
            login = f"gh-{emp.lower()}"
            repo.map_identity(login, emp)
            active_days = list(days)
            if arch == "quiet":
                active_days = days[:15]                                              # stops 5 working days before as_of
            elif arch == "sporadic":
                active_days = [d for k, d in enumerate(days) if k % 5 in (0, 2, 4)]
            for k, d in enumerate(active_days):
                done, planned, blockers, bstatus = _text(rng), _text(rng), "", "none"
                if arch == "carryover":
                    planned = "Finish payment gateway integration tests for checkout"
                if arch == "blocker" and d >= days[-6]:
                    blockers, bstatus = "Waiting for API credentials from the vendor to continue integration", "open"
                repo.upsert_standup(emp, pid, d.isoformat(), done, planned, blockers, bstatus, min(100, 40 + k * 2), float(rng.choice([6, 7, 7.5, 8])))
                if arch != "no_github" and rng.random() < 0.8:
                    for j in range(rng.randint(1, 3)):
                        et = rng.choices(["commit", "pr_merged", "review", "pr_opened"], [6, 2, 2, 1])[0]
                        events.append({"event_id": f"{emp}-{d.isoformat()}-{j}", "github_login": login, "repo": f"sim-corp/{slug}", "event_type": et,
                                       "title": _text(rng)[:80], "url": f"https://github.com/sim-corp/{slug}/pull/{rng.randint(1, 900)}",
                                       "event_ts": f"{d.isoformat()}T1{j}:00:00Z", "additions": rng.randint(5, 220), "deletions": rng.randint(0, 80)})
            if arch in FLAG_FOR:
                manifest["flags"].append((pid, FLAG_FOR[arch], emp))
        repo.import_github_events(events)
    manifest["flags"] = sorted(manifest["flags"])
    return manifest
