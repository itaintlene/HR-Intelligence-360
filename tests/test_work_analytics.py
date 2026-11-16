"""Work tracking analytics vs. seeded ground truth (no LLM involved)."""
import json
from datetime import date

import pytest

from hr360.data.engine import make_engine
from hr360.work import analytics
from hr360.work.repo import WorkRepo
from hr360.work.seed import PLAN, seed_work

AS_OF = date(2026, 11, 16)


@pytest.fixture(scope="module")
def world(ctx, tmp_path_factory):
    repo = WorkRepo(make_engine(tmp_path_factory.mktemp("work") / "w.db"))
    emps = ctx.db.employees()["employee_id"].tolist()
    manifest = seed_work(repo, emps, ["EMP-1001", "EMP-1002", "EMP-1003"], AS_OF)
    return repo, ctx.db.leave_requests(), manifest


def status(world, pid):
    repo, leaves, _ = world
    return analytics.project_status(repo, leaves, pid, AS_OF)


def test_working_days_skip_weekends():
    days = analytics.working_days(date(2026, 11, 16), 6)  # Mon 16th
    assert len(days) == 6 and all(d.weekday() < 5 for d in days) and days[-1] == date(2026, 11, 16)


@pytest.mark.parametrize("pid,health", [(p, v[1]) for p, v in PLAN.items()])
def test_schedule_status_matches_seeded_health(world, pid, health):
    assert status(world, pid)["progress"]["schedule_status"] == health


def test_flags_match_ground_truth_exactly(world):
    got = sorted((pid, f["type"], f["employee_id"]) for pid in PLAN for f in status(world, pid)["flags"]
                 if f["type"] in ("quiet_member", "stale_blocker", "high_carryover", "activity_mismatch"))
    assert got == world[2]["flags"]


def test_control_project_has_no_flags(world):
    s = status(world, "PRJ-101")
    assert s["flags"] == [] and s["blockers"] == []


def test_blockers_have_age_and_owner(world):
    b = status(world, "PRJ-103")["blockers"]
    assert len(b) == 1 and b[0]["age_days"] >= 3 and "credentials" in b[0]["text"]


def test_members_listed_alphabetically_never_ranked(world):
    for pid in PLAN:
        ids = [m["employee_id"] for m in status(world, pid)["members"]]
        assert ids == sorted(ids)


def test_no_composite_score_anywhere(world):
    blob = json.dumps(status(world, "PRJ-102")) + json.dumps(analytics.person_record(world[0], world[1], "EMP-1010", AS_OF))
    for banned in ("score", "rank", "rating", "grade", "performance_index"):
        assert banned not in blob.lower().replace("not used in any rating", "").replace("not a performance rating", "").replace("no score or ranking", "")


def test_leave_excuses_missing_updates(world):
    repo, leaves, manifest = world
    quiet = next(e for e, a in manifest["members"]["PRJ-102"].items() if a == "quiet")
    import pandas as pd
    leave = pd.DataFrame([{"employee_id": quiet, "status": "Approved", "start_date": "2026-11-09", "end_date": "2026-11-16"}])
    s = analytics.project_status(repo, leave, "PRJ-102", AS_OF)
    assert not [f for f in s["flags"] if f["type"] == "quiet_member"]


def test_person_record_for_sporadic_member(world):
    repo, leaves, manifest = world
    emp = next(e for e, a in manifest["members"]["PRJ-105"].items() if a == "sporadic")
    rec = analytics.person_record(repo, leaves, emp, AS_OF)
    p = rec["projects"][0]
    assert p["stats"]["submission_rate"] == pytest.approx(0.6, abs=0.01)
    assert any(f["type"] == "low_submission" for f in rec["flags"]) and rec["disclaimer"]
    assert "not used in any rating" in p["github"]["note"]


def test_github_import_is_idempotent_and_resolves_identity(world):
    repo, _, manifest = world
    emp = next(iter(manifest["members"]["PRJ-101"]))
    ev = {"event_id": "x-1", "github_login": f"gh-{emp.lower()}", "repo": "sim-corp/customer-portal", "event_type": "commit", "title": "t",
          "event_ts": "2026-11-16T09:00:00Z", "additions": 3, "deletions": 1}
    a, b = repo.import_github_events([ev]), repo.import_github_events([ev])
    assert (a["added"], b["added"], b["updated"]) == (1, 0, 1)
    row = repo.github_events(employee_id=emp).query("event_id == 'x-1'").iloc[0]
    assert row["project_id"] == "PRJ-101"
    assert repo.import_github_events([{**ev, "event_id": "x-2", "github_login": "stranger"}])["unmapped_login"] == 1


def test_standup_upsert_is_one_row_per_day(world):
    repo, _, manifest = world
    emp = next(iter(manifest["members"]["PRJ-101"]))
    for text in ("v1", "v2"):
        repo.upsert_standup(emp, "PRJ-101", "2026-11-17", text, "plan", "", "none", 50, 7.0)
    rows = repo.standups(project_id="PRJ-101", employee_id=emp, since="2026-11-17")
    assert len(rows) == 1 and rows.iloc[0]["done_text"] == "v2"
