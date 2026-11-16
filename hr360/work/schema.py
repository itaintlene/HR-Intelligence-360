"""Work-tracking tables: projects, stand-ups, proof-of-work evidence, GitHub activity.
Kept in their own MetaData so re-seeding employee data never wipes stand-up history."""
from sqlalchemy import Column, Float, Integer, MetaData, String, Table, Text, UniqueConstraint

WORK_METADATA = MetaData()

projects = Table(
    "projects", WORK_METADATA,
    Column("project_id", String(32), primary_key=True),
    *[Column(c, Text) for c in ("name", "description", "manager_employee_id", "start_date", "target_date", "status", "repo")])

project_members = Table(
    "project_members", WORK_METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("project_id", String(32), nullable=False), Column("employee_id", String(32), nullable=False),
    Column("role_on_project", Text), UniqueConstraint("project_id", "employee_id"))

milestones = Table(
    "milestones", WORK_METADATA,
    Column("milestone_id", String(40), primary_key=True),
    *[Column(c, Text) for c in ("project_id", "name", "due_date", "status", "done_on")], Column("weight", Float, default=1.0))

standups = Table(
    "standups", WORK_METADATA,
    Column("standup_id", String(48), primary_key=True),
    Column("employee_id", String(32), nullable=False), Column("project_id", String(32), nullable=False),
    Column("entry_date", String(10), nullable=False),
    *[Column(c, Text) for c in ("done_text", "planned_text", "blockers_text", "blocker_status", "created_at", "updated_at")],
    Column("self_progress", Integer), Column("hours", Float),
    UniqueConstraint("employee_id", "project_id", "entry_date"))

evidence = Table(
    "evidence", WORK_METADATA,
    Column("evidence_id", String(40), primary_key=True),
    *[Column(c, Text) for c in ("standup_id", "employee_id", "project_id", "filename", "stored_path", "description", "uploaded_at",
                                "ai_summary", "analysis_method", "injection_flags", "review_status", "reviewed_by", "reviewed_at")])

github_identities = Table(
    "github_identities", WORK_METADATA,
    Column("github_login", String(64), primary_key=True), Column("employee_id", String(32), nullable=False))

github_events = Table(
    "github_events", WORK_METADATA,
    Column("event_id", String(80), primary_key=True),
    *[Column(c, Text) for c in ("github_login", "employee_id", "repo", "project_id", "event_type", "title", "url", "event_ts")],
    Column("additions", Integer), Column("deletions", Integer))
