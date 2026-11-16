"""SQLite data access (PostgreSQL later: swap the connection factory, keep the queries)."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    employee_id TEXT PRIMARY KEY, name TEXT, email TEXT, department TEXT, designation TEXT,
    manager_id TEXT, joining_date TEXT, probation_end TEXT, employment_status TEXT,
    work_location TEXT, salary_band TEXT, national_id TEXT
);
CREATE TABLE IF NOT EXISTS documents (
    doc_id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT, doc_type TEXT,
    issue_date TEXT, expiry_date TEXT, status TEXT
);
CREATE TABLE IF NOT EXISTS leave_requests (
    leave_id TEXT PRIMARY KEY, employee_id TEXT, leave_type TEXT, start_date TEXT,
    end_date TEXT, days REAL, status TEXT, submitted_on TEXT
);
"""

# employees columns that must never be shown unmasked / sent to an LLM
SENSITIVE_COLUMNS = ("national_id", "salary_band")


class HRDatabase:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def init_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as c, c:
            c.executescript(SCHEMA)

    def exists(self) -> bool:
        if not self.path.exists():
            return False
        with closing(self.connect()) as c:
            row = c.execute("SELECT name FROM sqlite_master WHERE name='employees'").fetchone()
        return row is not None

    def _df(self, sql: str, params: tuple = ()) -> pd.DataFrame:
        with closing(self.connect()) as c:
            return pd.read_sql_query(sql, c, params=params)

    # --- read APIs used by agents (tools) ---
    def employees(self) -> pd.DataFrame:
        return self._df("SELECT * FROM employees ORDER BY employee_id")

    def documents(self) -> pd.DataFrame:
        return self._df("SELECT * FROM documents ORDER BY employee_id, doc_type")

    def leave_requests(self, status: str | None = None) -> pd.DataFrame:
        if status:
            return self._df("SELECT * FROM leave_requests WHERE status=? ORDER BY start_date", (status,))
        return self._df("SELECT * FROM leave_requests ORDER BY start_date")

    def get_employee(self, employee_id: str) -> dict | None:
        df = self._df("SELECT * FROM employees WHERE employee_id=?", (employee_id,))
        return None if df.empty else df.iloc[0].to_dict()

    def employee_contact(self, employee_id: str) -> tuple[str | None, str | None]:
        """(first_name, email). Used only when materialising an approved email."""
        emp = self.get_employee(employee_id)
        if not emp:
            return None, None
        first = (emp.get("name") or "").split(" ")[0] or None
        return first, emp.get("email")

    def recent_joiners(self, as_of, days: int = 30) -> list[str]:
        df = self.employees()
        if df.empty:
            return []
        jd = pd.to_datetime(df["joining_date"], errors="coerce")
        cutoff = pd.Timestamp(as_of) - pd.Timedelta(days=days)
        mask = (jd >= cutoff) & (jd <= pd.Timestamp(as_of))
        return df.loc[mask, "employee_id"].tolist()


def public_employee_view(df: pd.DataFrame, full: bool = False) -> pd.DataFrame:
    """RBAC-aware projection of employee records for display."""
    from hr360.security.rbac import mask_email, mask_id

    out = df.copy()
    if full:
        return out
    if "national_id" in out:
        out["national_id"] = out["national_id"].map(mask_id)
    if "email" in out:
        out["email"] = out["email"].map(mask_email)
    return out.drop(columns=[c for c in ("salary_band",) if c in out], errors="ignore")
