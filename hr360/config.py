"""Central configuration. Everything is overridable by environment variables or by
constructing ``Settings`` explicitly (tests do the latter)."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


def _env_date(name: str) -> date | None:
    raw = os.getenv(name)
    return date.fromisoformat(raw) if raw else None


@dataclass
class Settings:
    db_path: Path = field(default_factory=lambda: Path(os.getenv("HR360_DB", ROOT / "data" / "hr360.db")))
    # audit log + request registry (kept apart so re-seeding synthetic data never wipes them)
    ops_db_path: Path = field(default_factory=lambda: Path(os.getenv("HR360_OPS_DB", ROOT / "data" / "ops.db")))
    checkpoint_path: Path = field(
        default_factory=lambda: Path(os.getenv("HR360_CHECKPOINT_DB", ROOT / "data" / "checkpoints.db"))
    )
    rules_path: Path = ROOT / "hr360" / "rules" / "hr_rules.yaml"
    policy_dir: Path = ROOT / "data" / "policies"
    index_dir: Path = ROOT / "data" / "index"
    reports_dir: Path = ROOT / "reports"
    outbox_path: Path = ROOT / "data" / "outbox.jsonl"
    sample_docs_dir: Path = ROOT / "data" / "sample_docs"
    log_dir: Path = ROOT / "logs"
    # "auto" -> try sentence-transformers, fall back to a hashing embedder
    embeddings_backend: str = field(default_factory=lambda: os.getenv("HR360_EMBEDDINGS", "auto"))
    # "auto" | "openai" | "ollama" | "none"
    llm_backend: str = field(default_factory=lambda: os.getenv("HR360_LLM", "auto"))
    as_of: date = field(default_factory=lambda: _env_date("HR360_AS_OF") or date.today())
    max_steps: int = 12          # supervisor dispatch limit (infinite-loop guard)
    node_retries: int = 1        # extra attempts per agent node before fallback
    policy_top_k: int = 4

    def ensure_dirs(self) -> None:
        for p in (self.index_dir, self.reports_dir, self.log_dir, Path(self.db_path).parent):
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
