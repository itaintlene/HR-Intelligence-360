"""Create the synthetic database and sample documents.   Usage: python scripts/seed.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hr360.config import Settings  # noqa: E402
from hr360.data.sample_docs import generate_sample_docs  # noqa: E402
from hr360.data.synthetic import build_database  # noqa: E402


def main() -> None:
    s = Settings()
    s.ensure_dirs()
    db = build_database(s.db_path, s.as_of)
    docs = generate_sample_docs(s.sample_docs_dir, db, s.as_of)
    print(f"Database: {s.db_path}  (as-of {s.as_of})")
    print(f"Sample documents ({len(docs)}) in {s.sample_docs_dir}")


if __name__ == "__main__":
    main()
