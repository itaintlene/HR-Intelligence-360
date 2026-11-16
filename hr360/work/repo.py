"""Data access for work tracking (SQLite or Postgres via the shared engine)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import delete, insert, select, text, update

from hr360.work import schema as w


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class WorkRepo:
    def __init__(self, engine):
        self.engine = engine
        w.WORK_METADATA.create_all(engine)

    def _df(self, sql: str, params: dict | None = None) -> pd.DataFrame:
        with self.engine.connect() as c:
            return pd.read_sql_query(text(sql), c, params=params or {})

    # ---------------------------------------------------------------- projects
    def projects(self) -> pd.DataFrame:
        return self._df("SELECT * FROM projects ORDER BY project_id")

    def project(self, project_id: str) -> dict | None:
        df = self._df("SELECT * FROM projects WHERE project_id=:p", {"p": project_id})
        return None if df.empty else df.iloc[0].to_dict()

    def members(self, project_id: str | None = None) -> pd.DataFrame:
        if project_id:
            return self._df("SELECT * FROM project_members WHERE project_id=:p ORDER BY employee_id", {"p": project_id})
        return self._df("SELECT * FROM project_members ORDER BY project_id, employee_id")

    def projects_of_member(self, employee_id: str) -> list[str]:
        return self._df("SELECT project_id FROM project_members WHERE employee_id=:e", {"e": employee_id})["project_id"].tolist()

    def milestones(self, project_id: str | None = None) -> pd.DataFrame:
        if project_id:
            return self._df("SELECT * FROM milestones WHERE project_id=:p ORDER BY due_date", {"p": project_id})
        return self._df("SELECT * FROM milestones ORDER BY project_id, due_date")

    def create_project(self, row: dict, members: list[dict] | None = None, milestones: list[dict] | None = None) -> None:
        with self.engine.begin() as c:
            c.execute(insert(w.projects).values(**row))
            for m in members or []:
                c.execute(insert(w.project_members).values(project_id=row["project_id"], **m))
            for i, ms in enumerate(milestones or [], start=1):
                c.execute(insert(w.milestones).values(milestone_id=f"{row['project_id']}-M{i}", project_id=row["project_id"], **ms))

    def add_member(self, project_id: str, employee_id: str, role: str = "contributor") -> None:
        with self.engine.begin() as c:
            c.execute(delete(w.project_members).where((w.project_members.c.project_id == project_id) & (w.project_members.c.employee_id == employee_id)))
            c.execute(insert(w.project_members).values(project_id=project_id, employee_id=employee_id, role_on_project=role))

    def set_milestone_status(self, milestone_id: str, status: str, done_on: str | None) -> bool:
        with self.engine.begin() as c:
            r = c.execute(update(w.milestones).where(w.milestones.c.milestone_id == milestone_id).values(status=status, done_on=done_on))
        return r.rowcount > 0

    # ---------------------------------------------------------------- standups
    def upsert_standup(self, employee_id: str, project_id: str, entry_date: str, done: str, planned: str, blockers: str,
                       blocker_status: str, self_progress: int | None, hours: float | None) -> str:
        sid = f"SU-{employee_id}-{project_id}-{entry_date}"
        now = _now()
        vals = dict(employee_id=employee_id, project_id=project_id, entry_date=entry_date, done_text=done, planned_text=planned,
                    blockers_text=blockers, blocker_status=blocker_status, self_progress=self_progress, hours=hours, updated_at=now)
        with self.engine.begin() as c:
            if c.execute(select(w.standups.c.standup_id).where(w.standups.c.standup_id == sid)).first():
                c.execute(update(w.standups).where(w.standups.c.standup_id == sid).values(**vals))
            else:
                c.execute(insert(w.standups).values(standup_id=sid, created_at=now, **vals))
        return sid

    def standups(self, project_id: str | None = None, employee_id: str | None = None, since: str | None = None) -> pd.DataFrame:
        sql, p = "SELECT * FROM standups WHERE 1=1", {}
        for col, val in (("project_id", project_id), ("employee_id", employee_id)):
            if val:
                sql += f" AND {col}=:{col}"
                p[col] = val
        if since:
            sql += " AND entry_date>=:since"
            p["since"] = since
        return self._df(sql + " ORDER BY entry_date, employee_id", p)

    def get_standup(self, standup_id: str) -> dict | None:
        df = self._df("SELECT * FROM standups WHERE standup_id=:s", {"s": standup_id})
        return None if df.empty else df.iloc[0].to_dict()

    # ---------------------------------------------------------------- evidence
    def add_evidence(self, standup: dict, filename: str, stored_path: str, description: str, analysis: dict) -> dict:
        row = dict(evidence_id=f"EV-{uuid.uuid4().hex[:10]}", standup_id=standup["standup_id"], employee_id=standup["employee_id"],
                   project_id=standup["project_id"], filename=filename, stored_path=stored_path, description=description,
                   uploaded_at=_now(), ai_summary=analysis["summary"], analysis_method=analysis["method"],
                   injection_flags=json.dumps(analysis["injection_flags"]), review_status="pending")
        with self.engine.begin() as c:
            c.execute(insert(w.evidence).values(**row))
        return row

    def evidence(self, employee_id: str | None = None, project_id: str | None = None, standup_id: str | None = None) -> pd.DataFrame:
        sql, p = "SELECT * FROM evidence WHERE 1=1", {}
        for col, val in (("employee_id", employee_id), ("project_id", project_id), ("standup_id", standup_id)):
            if val:
                sql += f" AND {col}=:{col}"
                p[col] = val
        return self._df(sql + " ORDER BY uploaded_at", p)

    def get_evidence(self, evidence_id: str) -> dict | None:
        df = self._df("SELECT * FROM evidence WHERE evidence_id=:e", {"e": evidence_id})
        return None if df.empty else df.iloc[0].to_dict()

    def review_evidence(self, evidence_id: str, status: str, reviewer: str) -> bool:
        with self.engine.begin() as c:
            r = c.execute(update(w.evidence).where(w.evidence.c.evidence_id == evidence_id)
                          .values(review_status=status, reviewed_by=reviewer, reviewed_at=_now()))
        return r.rowcount > 0

    # ---------------------------------------------------------------- GitHub
    def map_identity(self, login: str, employee_id: str) -> None:
        with self.engine.begin() as c:
            c.execute(delete(w.github_identities).where(w.github_identities.c.github_login == login))
            c.execute(insert(w.github_identities).values(github_login=login, employee_id=employee_id))

    def identities(self) -> dict[str, str]:
        df = self._df("SELECT * FROM github_identities")
        return dict(zip(df["github_login"], df["employee_id"]))

    def import_github_events(self, events: list[dict]) -> dict:
        """Idempotent upsert by event_id. Resolves employee via identity map and project via repo."""
        ids = self.identities()
        repos = {r["repo"]: r["project_id"] for r in self.projects().to_dict("records") if r.get("repo")}
        added = updated = unmapped = 0
        with self.engine.begin() as c:
            for e in events:
                emp = ids.get(e["github_login"])
                row = dict(event_id=e["event_id"], github_login=e["github_login"], employee_id=emp, repo=e.get("repo"),
                           project_id=repos.get(e.get("repo")), event_type=e["event_type"], title=(e.get("title") or "")[:300],
                           url=e.get("url"), event_ts=e["event_ts"], additions=int(e.get("additions") or 0), deletions=int(e.get("deletions") or 0))
                unmapped += emp is None
                if c.execute(select(w.github_events.c.event_id).where(w.github_events.c.event_id == e["event_id"])).first():
                    c.execute(update(w.github_events).where(w.github_events.c.event_id == e["event_id"]).values(**row))
                    updated += 1
                else:
                    c.execute(insert(w.github_events).values(**row))
                    added += 1
        return {"added": added, "updated": updated, "unmapped_login": unmapped}

    def github_events(self, employee_id: str | None = None, project_id: str | None = None, since: str | None = None) -> pd.DataFrame:
        sql, p = "SELECT * FROM github_events WHERE 1=1", {}
        for col, val in (("employee_id", employee_id), ("project_id", project_id)):
            if val:
                sql += f" AND {col}=:{col}"
                p[col] = val
        if since:
            sql += " AND event_ts>=:since"
            p["since"] = since
        return self._df(sql + " ORDER BY event_ts", p)
