"""Deterministic work analytics. NO LLM, NO composite performance score, NO ranking.

Everything here is a *signal with evidence* for a human reviewer: submission consistency, open blockers and their age,
planned-vs-done carry-over, milestone schedule, GitHub activity counts. Lines changed are returned as raw context only
and never feed any rating (they are a poor proxy for impact).
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

import pandas as pd

QUIET_AFTER_WORKING_DAYS = 3
STALE_BLOCKER_DAYS = 3
CARRYOVER_MIN_PAIRS = 4
CARRYOVER_RATE_FLAG = 0.5
LOW_SUBMISSION_RATE = 0.7
DISCLAIMER = ("These are signals for human review, not a performance rating. No score or ranking is computed; "
              "context (leave, non-code work, ramp-up, team load) must be considered by a person.")
_STOP = set("the a an and or of to in on for with is are was were be been it this that i we my our will today yesterday working worked work".split())


def clean(obj):
    """Make pandas/numpy output JSON- and msgpack-safe: NaN/NaT -> None, numpy scalars -> Python."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        try:
            obj = obj.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(obj, float) and obj != obj:
        return None
    return None if obj is pd.NaT else obj


def _d(x) -> date:
    return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


def working_days(end: date, n: int) -> list[date]:
    """The last ``n`` weekdays up to and including ``end`` (oldest first)."""
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def tokens(text: str | None) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in _STOP and len(t) > 2}


def jaccard(a: str | None, b: str | None) -> float:
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def leave_days(leaves: pd.DataFrame, employee_id: str) -> set[date]:
    out: set[date] = set()
    if leaves is None or leaves.empty:
        return out
    for _, r in leaves[(leaves["employee_id"] == employee_id) & (leaves["status"] == "Approved")].iterrows():
        d, end = _d(r["start_date"]), _d(r["end_date"])
        while d <= end:
            out.add(d)
            d += timedelta(days=1)
    return out


def _flag(kind: str, severity: str, employee_id: str | None, message: str, evidence: dict) -> dict:
    return {"type": kind, "severity": severity, "employee_id": employee_id, "message": message, "evidence": evidence}


def _member_stats(su: pd.DataFrame, emp: str, days: list[date], leaves: pd.DataFrame) -> dict:
    mine = su[su["employee_id"] == emp].sort_values("entry_date")
    off = leave_days(leaves, emp)
    expected = [d for d in days if d not in off]
    submitted = {_d(x) for x in mine["entry_date"]}
    got = [d for d in expected if d in submitted]
    pairs = carry = 0
    rows = mine.to_dict("records")
    for prev, nxt in zip(rows, rows[1:]):
        if not tokens(prev["planned_text"]):
            continue
        pairs += 1
        if jaccard(prev["planned_text"], nxt["planned_text"]) >= 0.6 and jaccard(prev["planned_text"], nxt["done_text"]) < 0.3:
            carry += 1
    return {"days_expected": len(expected), "days_submitted": len(got),
            "submission_rate": round(len(got) / len(expected), 2) if expected else None,
            "missing_days": [d.isoformat() for d in expected if d not in submitted],
            "carryover_pairs": pairs, "carryover_count": carry,
            "carryover_rate": round(carry / pairs, 2) if pairs >= CARRYOVER_MIN_PAIRS else None,
            "last_update": mine["entry_date"].max() if not mine.empty else None}


def _open_blocker(history: pd.DataFrame, as_of: date) -> dict | None:
    """Latest still-open blocker for one person on one project, with the date it first appeared."""
    rows = history.sort_values("entry_date").to_dict("records")
    if not rows:
        return None
    last = rows[-1]
    if not (last["blockers_text"] or "").strip() or last["blocker_status"] != "open":
        return None
    first = last["entry_date"]
    for r in reversed(rows[:-1]):
        if (r["blockers_text"] or "").strip() and r["blocker_status"] == "open" and jaccard(r["blockers_text"], last["blockers_text"]) >= 0.4:
            first = r["entry_date"]
        else:
            break
    return {"text": last["blockers_text"], "first_seen": first, "last_seen": last["entry_date"], "age_days": (as_of - _d(first)).days}


def _github_counts(ev: pd.DataFrame) -> dict:
    t = ev["event_type"].value_counts().to_dict() if not ev.empty else {}
    return {"commits": int(t.get("commit", 0)), "prs_opened": int(t.get("pr_opened", 0)), "prs_merged": int(t.get("pr_merged", 0)),
            "reviews": int(t.get("review", 0)), "issues_closed": int(t.get("issue_closed", 0)), "events": int(len(ev))}


# ------------------------------------------------------------------------------------ project
def project_status(repo, leaves: pd.DataFrame, project_id: str, as_of: date, window: int = 10) -> dict:
    proj = repo.project(project_id)
    if proj is None:
        raise KeyError(project_id)
    members, ms = repo.members(project_id), repo.milestones(project_id)
    days = working_days(as_of, window)
    history = repo.standups(project_id=project_id, since=(as_of - timedelta(days=60)).isoformat())
    in_window = history[history["entry_date"] >= days[0].isoformat()]
    gh_all = repo.github_events(project_id=project_id, since=(as_of - timedelta(days=2 * window + 4)).isoformat())
    ids = repo.identities()
    login_of = {e: lg for lg, e in ids.items()}

    # --- milestone progress vs. timeline
    total_w, done_w = float(ms["weight"].sum()), float(ms[ms["status"] == "done"]["weight"].sum())
    pct = round(100 * done_w / total_w) if total_w else None
    start, target = _d(proj["start_date"]), _d(proj["target_date"])
    span = max((target - start).days, 1)
    expected = round(100 * min(max((as_of - start).days / span, 0), 1))
    overdue = ms[(ms["status"] != "done") & (ms["due_date"] < as_of.isoformat())]
    delta = (pct - expected) if pct is not None else None

    flags: list[dict] = []
    blockers, member_rows = [], []
    for emp in members["employee_id"]:
        stats = _member_stats(in_window, emp, days, leaves)
        mine_hist = history[history["employee_id"] == emp]
        ob = _open_blocker(mine_hist, as_of)
        if ob:
            blockers.append({"employee_id": emp, **ob})
            if ob["age_days"] >= STALE_BLOCKER_DAYS:
                flags.append(_flag("stale_blocker", "attention", emp, f"Blocker open for {ob['age_days']} days: {ob['text'][:120]}", ob))
        # quiet: nothing in the last N working days (excluding leave)
        recent = [d for d in days[-QUIET_AFTER_WORKING_DAYS:] if d not in leave_days(leaves, emp)]
        got_recent = {_d(x) for x in in_window[in_window["employee_id"] == emp]["entry_date"]}
        quiet = bool(recent) and not any(d in got_recent for d in recent)
        if quiet:
            lu = stats["last_update"]
            flags.append(_flag("quiet_member", "watch", emp, f"No stand-up in the last {len(recent)} working days"
                               + (f" (last update {lu})" if lu else " (none in window)"), {"last_update": lu, "days_checked": [d.isoformat() for d in recent]}))
        if stats["carryover_rate"] is not None and stats["carryover_rate"] >= CARRYOVER_RATE_FLAG:
            flags.append(_flag("high_carryover", "watch", emp, f"Same plan repeated without matching 'done' in {stats['carryover_count']}/{stats['carryover_pairs']} consecutive updates",
                               {"carryover_rate": stats["carryover_rate"]}))
        gh_mine = gh_all[(gh_all["employee_id"] == emp) & (gh_all["event_ts"] >= days[0].isoformat())] if not gh_all.empty else gh_all
        counts = _github_counts(gh_mine)
        if proj.get("repo") and emp in login_of and stats["days_submitted"] >= 5 and counts["events"] == 0:
            flags.append(_flag("activity_mismatch", "info", emp, f"{stats['days_submitted']} update days but no GitHub activity in the window (may be non-code work)",
                               {"days_submitted": stats["days_submitted"]}))
        member_rows.append({"employee_id": emp, "role": members[members["employee_id"] == emp].iloc[0]["role_on_project"], **stats,
                            "quiet": quiet, "open_blocker": bool(ob), "github": counts, "has_github_identity": emp in login_of})

    for _, m in overdue.iterrows():
        flags.append(_flag("overdue_milestone", "attention", None, f"Milestone '{m['name']}' was due {m['due_date']}", {"milestone_id": m["milestone_id"]}))
    stale = any(b["age_days"] >= STALE_BLOCKER_DAYS for b in blockers)
    if proj["status"] == "done" or pct == 100:
        schedule = "done"
    elif (len(overdue) and delta is not None and delta <= -15) or (delta is not None and delta <= -25):
        schedule = "behind"
    elif len(overdue) or (delta is not None and delta <= -10) or stale:
        schedule = "at_risk"
    else:
        schedule = "on_track"
    if schedule in ("behind", "at_risk") and delta is not None:
        flags.append(_flag("schedule", "attention" if schedule == "behind" else "watch", None,
                           f"Milestone progress {pct}% vs {expected}% expected by timeline ({schedule.replace('_', ' ')})",
                           {"pct": pct, "expected_pct": expected}))

    prev_from = (days[0] - timedelta(days=window + 2)).isoformat()
    prev = gh_all[(gh_all["event_ts"] >= prev_from) & (gh_all["event_ts"] < days[0].isoformat())] if not gh_all.empty else gh_all
    cur = gh_all[gh_all["event_ts"] >= days[0].isoformat()] if not gh_all.empty else gh_all
    return clean({"project": {k: proj[k] for k in ("project_id", "name", "manager_employee_id", "start_date", "target_date", "status", "repo")},
            "progress": {"pct_complete": pct, "expected_pct": expected, "delta": delta, "schedule_status": schedule},
            "milestones": [{**r, "overdue": bool(r["status"] != "done" and r["due_date"] < as_of.isoformat())} for r in ms.to_dict("records")],
            "blockers": sorted(blockers, key=lambda b: -b["age_days"]),
            "members": sorted(member_rows, key=lambda m: m["employee_id"]),   # alphabetical on purpose: never ordered by "performance"
            "flags": flags, "github": {"current": _github_counts(cur), "previous": _github_counts(prev)},
            "window": {"working_days": window, "from": days[0].isoformat(), "to": days[-1].isoformat()}, "disclaimer": DISCLAIMER})


# ------------------------------------------------------------------------------------ person
def person_record(repo, leaves: pd.DataFrame, employee_id: str, as_of: date, window: int = 20, project_id: str | None = None) -> dict:
    days = working_days(as_of, window)
    since = days[0].isoformat()
    pids = [project_id] if project_id else repo.projects_of_member(employee_id)
    ev_all = repo.evidence(employee_id=employee_id)
    projects = []
    for pid in pids:
        proj = repo.project(pid)
        if proj is None:
            continue
        su = repo.standups(project_id=pid, employee_id=employee_id, since=since)
        hist = repo.standups(project_id=pid, employee_id=employee_id, since=(as_of - timedelta(days=60)).isoformat())
        stats = _member_stats(su, employee_id, days, leaves)
        ob = _open_blocker(hist, as_of)
        gh = repo.github_events(employee_id=employee_id, project_id=pid, since=since)
        evs = ev_all[ev_all["project_id"] == pid] if not ev_all.empty else ev_all
        ev_by_su = {}
        for e in evs.to_dict("records"):
            e["injection_flags"] = json.loads(e["injection_flags"] or "[]")
            ev_by_su.setdefault(e["standup_id"], []).append({k: e[k] for k in ("evidence_id", "filename", "description", "ai_summary", "analysis_method",
                                                                                 "review_status", "reviewed_by", "injection_flags", "uploaded_at")})
        timeline = [{"standup_id": r["standup_id"], "date": r["entry_date"], "done": r["done_text"], "planned": r["planned_text"], "blockers": r["blockers_text"],
                     "blocker_status": r["blocker_status"], "self_progress": r["self_progress"], "hours": r["hours"], "evidence": ev_by_su.get(r["standup_id"], [])}
                    for r in su.sort_values("entry_date", ascending=False).to_dict("records")]
        flags = []
        if stats["submission_rate"] is not None and stats["submission_rate"] < LOW_SUBMISSION_RATE:
            flags.append(_flag("low_submission", "watch", employee_id, f"{stats['days_submitted']}/{stats['days_expected']} expected stand-ups submitted", {"missing_days": stats["missing_days"][-8:]}))
        if ob and ob["age_days"] >= STALE_BLOCKER_DAYS:
            flags.append(_flag("stale_blocker", "attention", employee_id, f"Blocker open {ob['age_days']} days: {ob['text'][:120]}", ob))
        if stats["carryover_rate"] is not None and stats["carryover_rate"] >= CARRYOVER_RATE_FLAG:
            flags.append(_flag("high_carryover", "watch", employee_id, "Repeated plans without matching progress", {"carryover_rate": stats["carryover_rate"]}))
        unreviewed = int((evs["review_status"] == "pending").sum()) if not evs.empty else 0
        gh_counts = _github_counts(gh)
        projects.append({"project": {k: proj[k] for k in ("project_id", "name", "manager_employee_id", "repo")}, "stats": stats, "open_blocker": ob,
                         "github": {**gh_counts, "raw_lines_added": int(gh["additions"].sum()) if not gh.empty else 0,
                                    "raw_lines_removed": int(gh["deletions"].sum()) if not gh.empty else 0,
                                    "note": "Line counts are raw context only - not a measure of impact and not used in any rating.",
                                    "recent": gh.sort_values("event_ts", ascending=False).head(15)[["event_type", "title", "url", "event_ts", "repo"]].to_dict("records")},
                         "evidence_count": int(len(evs)), "evidence_unreviewed": unreviewed, "timeline": timeline, "flags": flags})
    return clean({"employee_id": employee_id, "window": {"working_days": window, "from": since, "to": days[-1].isoformat()}, "projects": projects,
                  "flags": [f for p in projects for f in p["flags"]], "disclaimer": DISCLAIMER})
