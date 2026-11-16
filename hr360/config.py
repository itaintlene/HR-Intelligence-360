"""Central configuration. Everything is overridable by environment variables or by
constructing ``Settings`` explicitly (tests do the latter)."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:  # load local secrets/config from .env (real environment variables always win)
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:  # python-dotenv is optional
    pass
TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


def _env_date(name: str) -> date | None:
    raw = os.getenv(name)
    return date.fromisoformat(raw) if raw else None


ON_SERVERLESS = bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
_TMP = Path("/tmp/hr360")  # the only writable location on serverless hosts


@dataclass
class Settings:
    # Postgres/Neon URL. When set, ALL state (HR data, audit log, requests, checkpoints) lives there.
    database_url: str | None = field(default_factory=lambda: os.getenv("DATABASE_URL") or None)
    db_path: Path = field(default_factory=lambda: Path(os.getenv("HR360_DB", ROOT / "data" / "hr360.db")))
    # audit log + request registry (kept apart so re-seeding synthetic data never wipes them)
    ops_db_path: Path = field(default_factory=lambda: Path(os.getenv("HR360_OPS_DB", ROOT / "data" / "ops.db")))
    checkpoint_path: Path = field(
        default_factory=lambda: Path(os.getenv("HR360_CHECKPOINT_DB", ROOT / "data" / "checkpoints.db"))
    )
    rules_path: Path = ROOT / "hr360" / "rules" / "hr_rules.yaml"
    policy_dir: Path = ROOT / "data" / "policies"
    index_dir: Path = field(default_factory=lambda: _TMP / "index" if ON_SERVERLESS else ROOT / "data" / "index")
    reports_dir: Path = field(default_factory=lambda: _TMP / "reports" if ON_SERVERLESS else ROOT / "reports")
    outbox_path: Path = field(default_factory=lambda: _TMP / "outbox.jsonl" if ON_SERVERLESS else ROOT / "data" / "outbox.jsonl")
    sample_docs_dir: Path = ROOT / "data" / "sample_docs"
    log_dir: Path = field(default_factory=lambda: _TMP / "logs" if ON_SERVERLESS else ROOT / "logs")
    # "auto" -> try sentence-transformers, fall back to a hashing embedder
    embeddings_backend: str = field(default_factory=lambda: os.getenv("HR360_EMBEDDINGS", "auto"))
    # "auto" | "openai" | "ollama" | "none"
    llm_backend: str = field(default_factory=lambda: os.getenv("HR360_LLM", "auto"))
    as_of: date = field(default_factory=lambda: _env_date("HR360_AS_OF") or date.today())
    max_steps: int = 12          # supervisor dispatch limit (infinite-loop guard)
    node_retries: int = 1        # extra attempts per agent node before fallback
    policy_top_k: int = 4

    @property
    def hr_target(self):
        return self.database_url or self.db_path

    @property
    def ops_target(self):
        return self.database_url or self.ops_db_path

    def ensure_dirs(self) -> None:
        dirs = [self.index_dir, self.reports_dir, self.log_dir]
        if not self.database_url:
            dirs.append(Path(self.db_path).parent)
        for p in dirs:
            Path(p).mkdir(parents=True, exist_ok=True)


def configure_tesseract() -> bool:
    """Point pytesseract at the Tesseract binary. Returns True if it is usable."""
    try:
        import pytesseract
    except ImportError:
        return False
    for cand in TESSERACT_CANDIDATES:
        if Path(cand).exists():
            pytesseract.pytesseract.tesseract_cmd = cand
            return True
    return shutil.which("tesseract") is not None
