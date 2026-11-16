"""Synthetic (fake) HR data with deliberately seeded anomalies.

``SEEDED_ISSUES`` is the ground truth used by the evaluation suite: rule_id -> employee ids
that the deterministic rules engine must flag.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import insert

from hr360.data import schema
from hr360.data.db import HRDatabase
from hr360.data.engine import is_url

FIRST = ["Aarav", "Priya", "Rohan", "Sneha", "Vikram", "Ananya", "Karan", "Meera", "Arjun", "Divya",
         "Rahul", "Neha", "Sanjay", "Pooja", "Amit", "Kavya", "Nikhil", "Isha", "Manish", "Tara"]
LAST = ["Sharma", "Patel", "Iyer", "Gupta", "Reddy", "Nair", "Singh", "Mehta", "Das", "Kapoor"]
DEPARTMENTS = {
    "Engineering": ["Software Engineer", "Senior Software Engineer", "QA Engineer", "DevOps Engineer"],
    "Human Resources": ["HR Executive", "HR Business Partner", "Recruiter"],
    "Finance": ["Financial Analyst", "Accountant", "Payroll Specialist"],
    "Sales": ["Sales Executive", "Account Manager", "Sales Manager"],
    "Marketing": ["Marketing Specialist", "Content Strategist", "Brand Manager"],
    "Operations": ["Operations Analyst", "Operations Manager", "Office Administrator"],
}
REQUIRED_DOCS = ["offer_letter", "id_proof", "address_proof", "tax_form", "nda", "bank_details", "education_certificate"]
LOCATIONS = ["Bengaluru", "Mumbai", "Pune", "Remote"]

# rule_id -> employees that MUST be flagged (used by evaluation + tests)
SEEDED_ISSUES: dict[str, list[str]] = {
    "R001_MANDATORY_FIELDS": ["EMP-1014"],
    "R002_REQUIRED_DOCUMENTS": ["EMP-1005", "EMP-1035", "EMP-1036", "EMP-1031", "EMP-1032"],
    "R003_DOCUMENT_EXPIRY": ["EMP-1008", "EMP-1011"],
    "R004_PROBATION_DATES": ["EMP-1020"],
    "R005_FUTURE_JOINING_ACTIVE": ["EMP-1023"],
    "R006_MANAGER_REFERENCE": ["EMP-1017"],
    "R007_DUPLICATE_EMAIL": ["EMP-1026", "EMP-1027"],
    "R008_VALID_VALUES": ["EMP-1029"],
    "R009_OFFER_LETTER_DATE": ["EMP-1030"],
}


def _d(x: date | None) -> str | None:
    return x.isoformat() if x else None


def build_database(target: Path | str, anchor: date, seed: int = 42) -> HRDatabase:
    """(Re)create the synthetic HR tables. ``target`` is a SQLite path or a Postgres URL.
    Dates are relative to ``anchor`` ("today")."""
    if not is_url(target) and Path(target).exists():
        Path(target).unlink()
    db = HRDatabase(target)
    db.drop_all()  # clears HR tables only (never audit/ops tables)
    db.init_schema()
    rng = random.Random(seed)

    employees: list[dict] = []
    docs: list[dict] = []
    dept_names = list(DEPARTMENTS)

    def add_employee(i: int, joined: date) -> dict:
        dept = dept_names[i % len(dept_names)]
        name = f"{FIRST[i % len(FIRST)]} {LAST[(i * 3) % len(LAST)]}"
        emp = {
            "employee_id": f"EMP-{1000 + i}", "name": name,
            "email": f"{name.lower().replace(' ', '.')}.{1000 + i}@example-corp.com",
            "department": dept, "designation": rng.choice(DEPARTMENTS[dept]),
            "manager_id": "EMP-1001" if i > 1 else None, "joining_date": _d(joined),
            "probation_end": _d(joined + timedelta(days=90)),
            "employment_status": "Active" if (anchor - joined).days > 90 else "Probation",
            "work_location": rng.choice(LOCATIONS), "salary_band": rng.choice(["B1", "B2", "B3", "B4"]),
            "national_id": f"SYN{rng.randint(10**7, 10**8 - 1)}",
        }
        employees.append(emp)
        return emp

    def add_docs(emp: dict, joined: date, skip: tuple[str, ...] = (), expiry_override: dict | None = None):
        for dt in REQUIRED_DOCS:
            if dt in skip:
                continue
            expiry = None
            if dt == "id_proof":
                expiry = anchor + timedelta(days=rng.randint(400, 2000))
            if expiry_override and dt in expiry_override:
                expiry = expiry_override[dt]
            offset = -rng.randint(3, 14) if dt == "offer_letter" else rng.randint(0, 3)  # offers precede joining
            docs.append({"employee_id": emp["employee_id"], "doc_type": dt,
                         "issue_date": _d(joined + timedelta(days=offset)),
                         "expiry_date": _d(expiry), "status": "received"})

    # 30 base employees (1001-1030), joined 60-900 days ago
    for i in range(1, 31):
        joined = anchor - timedelta(days=rng.randint(100, 900))
        emp = add_employee(i, joined)
        emp["_joined"] = joined
    # 6 recent joiners (1031-1036)
    recent_days = {31: 2, 32: 4, 33: 3, 34: 5, 35: 20, 36: 25}
    for i, days_ago in recent_days.items():
        joined = anchor - timedelta(days=days_ago)
        emp = add_employee(i, joined)
        emp["_joined"] = joined

    by_id = {e["employee_id"]: e for e in employees}
    # ---- documents (with anomalies) ----
    skip_map = {
        "EMP-1005": ("tax_form",),
        "EMP-1031": ("bank_details", "nda"),            # within grace -> potential
        "EMP-1032": ("education_certificate",),          # within grace -> potential
        "EMP-1033": (), "EMP-1034": (),
        "EMP-1035": ("tax_form", "bank_details", "nda"),  # overdue -> confirmed
        "EMP-1036": ("address_proof",),                   # overdue -> confirmed
    }
    expiry_map = {
        "EMP-1008": {"id_proof": anchor - timedelta(days=20)},   # expired
        "EMP-1011": {"id_proof": anchor + timedelta(days=15)},   # expiring soon
    }
    for emp in employees:
        add_docs(emp, emp["_joined"], skip_map.get(emp["employee_id"], ()), expiry_map.get(emp["employee_id"]))

    # ---- field-level anomalies ----
    by_id["EMP-1014"]["department"] = None                                   # missing mandatory
    by_id["EMP-1017"]["manager_id"] = "EMP-9999"                              # dangling manager
    by_id["EMP-1020"]["probation_end"] = _d(by_id["EMP-1020"]["_joined"] - timedelta(days=10))
    by_id["EMP-1023"]["joining_date"] = _d(anchor + timedelta(days=12))      # future + Active
    by_id["EMP-1023"]["probation_end"] = _d(anchor + timedelta(days=102))
    by_id["EMP-1023"]["employment_status"] = "Active"
    by_id["EMP-1027"]["email"] = by_id["EMP-1026"]["email"]                   # duplicate email
    by_id["EMP-1029"]["salary_band"] = "Z9"                                   # invalid value
    # offer letter dated 30 days after joining
    for d in docs:
        if d["employee_id"] == "EMP-1030" and d["doc_type"] == "offer_letter":
            d["issue_date"] = _d(by_id["EMP-1030"]["_joined"] + timedelta(days=30))

    # EMP-1023 joins in future: drop documents (not yet onboarded) is NOT seeded to keep ground truth clean
    for emp in employees:
        emp.pop("_joined", None)

    # ---- leave requests ----
    leaves = []
    types = ["Casual", "Sick", "Earned", "Casual"]
    for n in range(1, 13):
        emp_id = f"EMP-{1000 + rng.randint(2, 30)}"
        start = anchor + timedelta(days=rng.randint(3, 40))
        span = rng.randint(1, 5)
        leaves.append({"leave_id": f"LV-{n:03d}", "employee_id": emp_id, "leave_type": rng.choice(types),
                       "start_date": _d(start), "end_date": _d(start + timedelta(days=span - 1)),
                       "days": float(span), "status": "Pending" if n <= 8 else "Approved",
                       "submitted_on": _d(anchor - timedelta(days=rng.randint(0, 6)))})

    with db.engine.begin() as c:
        c.execute(insert(schema.employees), employees)
        c.execute(insert(schema.documents), docs)
        c.execute(insert(schema.leave_requests), leaves)
    return db
