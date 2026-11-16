"""HR data access (SQLite for dev/tests, Postgres/Neon when DATABASE_URL is set)."""
from __future__ import annotations

import pandas as pd
from sqlalchemy import inspect, text

from hr360.data.engine import make_engine
from hr360.data.schema import HR_METADATA

# employees columns that must never be shown unmasked / sent to an LLM
SENSITIVE_COLUMNS = ("national_id", "salary_band")


class HRDatabase:
    def __init__(self, target):
        """``target``: filesystem path, database URL, or an existing SQLAlchemy Engine."""
        self.engine = make_engine(target)

    def init_schema(self) -> None:
        HR_METADATA.create_all(self.engine)

    def drop_all(self) -> None:
        HR_METADATA.drop_all(self.engine)

    def exists(self) -> bool:
        return inspect(self.engine).has_table("employees")

    def has_data(self) -> bool:
        if not self.exists():
            return False
        with self.engine.connect() as c:
            return bool(c.execute(text("SELECT COUNT(*) FROM employees")).scalar())

    def _df(self, sql: str, params: dict | None = None) -> pd.DataFrame:
        with self.engine.connect() as c:
            return pd.read_sql_query(text(sql), c, params=params or {})

    # --- read APIs used by agents (tools) ---
    def employees(self) -> pd.DataFrame:
        return self._df("SELECT * FROM employees ORDER BY employee_id")

    def documents(self) -> pd.DataFrame:
        return self._df("SELECT * FROM documents ORDER BY employee_id, doc_type")

    def leave_requests(self, status: str | None = None) -> pd.DataFrame:
        if status:
            return self._df("SELECT * FROM leave_requests WHERE status=:s ORDER BY start_date", {"s": status})
        return self._df("SELECT * FROM leave_requests ORDER BY start_date")

    def get_employee(self, employee_id: str) -> dict | None:
        df = self._df("SELECT * FROM employees WHERE employee_id=:e", {"e": employee_id})
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
