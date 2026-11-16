"""Seed demo work-tracking data (6 projects, ~20 working days of stand-ups, GitHub activity) into the configured database.

    python scripts/seed_work.py            # refuses to overwrite existing work data
    python scripts/seed_work.py --reset    # wipes work tables first (stand-ups, evidence, GitHub events are lost!)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from hr360.config import Settings  # noqa: E402
from hr360.data.db import HRDatabase  # noqa: E402
from hr360.work.repo import WorkRepo  # noqa: E402
from hr360.work.schema import WORK_METADATA  # noqa: E402
from hr360.work.seed import seed_work  # noqa: E402


def main() -> None:
    s = Settings()
    db = HRDatabase(s.hr_target)
    if not db.has_data():
        sys.exit("No employee data found - run scripts/seed.py first.")
    if "--reset" in sys.argv:
        WORK_METADATA.drop_all(db.engine)
    repo = WorkRepo(db.engine)
    with db.engine.connect() as c:
        if c.execute(text("SELECT COUNT(*) FROM projects")).scalar():
            sys.exit("Work data already exists. Use --reset to replace it (this deletes stand-ups and evidence).")
    emps = db.employees()["employee_id"].tolist()
    leads = [e for e in ("EMP-1001", "EMP-1002", "EMP-1003") if e in emps] or emps[:3]
    m = seed_work(repo, emps, leads, s.as_of)
    print(f"Seeded {len(m['schedule'])} projects ({'Postgres' if s.database_url else s.db_path}); as-of {s.as_of}; project managers: {leads}")
    print("Planted signals:", *m["flags"], sep="\n  ")


if __name__ == "__main__":
    main()
