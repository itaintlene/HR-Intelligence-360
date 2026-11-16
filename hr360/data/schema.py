"""Table definitions (SQLAlchemy Core) - one schema, runs on SQLite (dev/tests) and Postgres/Neon (deploy)."""
from sqlalchemy import Column, Float, Integer, MetaData, String, Table, Text

HR_METADATA = MetaData()   # business data (re-seedable)
OPS_METADATA = MetaData()  # audit log, request registry, outbox (never wiped by re-seeding)

employees = Table(
    "employees", HR_METADATA,
    Column("employee_id", String(32), primary_key=True),
    *[Column(c, Text) for c in ("name", "email", "department", "designation", "manager_id", "joining_date",
                                "probation_end", "employment_status", "work_location", "salary_band", "national_id")])

documents = Table(
    "documents", HR_METADATA,
    Column("doc_id", Integer, primary_key=True, autoincrement=True),
    *[Column(c, Text) for c in ("employee_id", "doc_type", "issue_date", "expiry_date", "status")])

leave_requests = Table(
    "leave_requests", HR_METADATA,
    Column("leave_id", String(32), primary_key=True),
    Column("employee_id", Text), Column("leave_type", Text), Column("start_date", Text), Column("end_date", Text),
    Column("days", Float), Column("status", Text), Column("submitted_on", Text))

audit_log = Table(
    "audit_log", OPS_METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    *[Column(c, Text) for c in ("ts", "request_id", "actor", "role", "agent", "action", "detail")])

requests = Table(
    "requests", OPS_METADATA,
    Column("request_id", String(32), primary_key=True),
    *[Column(c, Text) for c in ("user_id", "role", "query", "task_type", "status", "created_at", "updated_at")])

outbox = Table(
    "outbox", OPS_METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    *[Column(c, Text) for c in ("ts", "request_id", "draft_id", "employee_id", "to_addr", "subject", "body",
                                "approved_by", "delivery", "provider_id")])
