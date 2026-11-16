import sys
from datetime import date
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hr360.agents.base import AgentContext  # noqa: E402
from hr360.config import Settings  # noqa: E402
from hr360.data.sample_docs import generate_sample_docs  # noqa: E402
from hr360.data.synthetic import build_database  # noqa: E402
from hr360.graph.runner import HRRunner  # noqa: E402
from hr360.llm.provider import LLMClient  # noqa: E402

ANCHOR = date(2026, 11, 16)


class FakeLLM(LLMClient):
    """Scripted LLM for testing the LLM code paths without network access."""

    def __init__(self, text: str | None = None, structured=None):
        super().__init__("none")
        self.text, self.structured, self.calls = text, structured, []

    @property
    def available(self) -> bool:
        return True

    def invoke_text(self, system, user):
        self.calls.append(("text", system, user))
        return self.text

    def invoke_structured(self, schema, system, user):
        self.calls.append(("structured", system, user))
        return self.structured


@pytest.fixture(scope="session")
def settings(tmp_path_factory) -> Settings:
    d = tmp_path_factory.mktemp("hr360")
    s = Settings(database_url=None, db_path=d / "hr.db", ops_db_path=d / "ops.db", checkpoint_path=d / "cp.db", index_dir=d / "index",
                 reports_dir=d / "reports", outbox_path=d / "outbox.jsonl", sample_docs_dir=d / "docs", log_dir=d / "logs",
                 embeddings_backend="hash", llm_backend="none", as_of=ANCHOR)
    s.ensure_dirs()
    db = build_database(s.hr_target, ANCHOR)
    generate_sample_docs(s.sample_docs_dir, db, ANCHOR)
    return s


@pytest.fixture(scope="session")
def ctx(settings) -> AgentContext:
    return AgentContext.build(settings, llm=LLMClient("none"))


@pytest.fixture()
def runner(ctx, settings) -> HRRunner:
    if settings.outbox_path.exists():
        settings.outbox_path.unlink()
    return HRRunner(ctx, checkpointer=MemorySaver())


@pytest.fixture(scope="session")
def sample_docs(settings) -> dict[str, str]:
    return {p.name: str(p) for p in settings.sample_docs_dir.iterdir()}


@pytest.fixture(autouse=True)
def _isolate_external_services(monkeypatch, request):
    """Tests must never use real credentials from .env or leak admin-page settings between tests."""
    for var in ("RESEND_API_KEY", "HR360_EMAIL_REDIRECT_TO", "HR360_EMAIL_LIVE", "CLERK_SECRET_KEY",
                "HR360_BOOTSTRAP_ADMIN_IDS", "LANGSMITH_TRACING", "LANGSMITH_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield
    if "settings" in request.fixturenames:  # reset DB-stored admin settings after tests that touched the session DB
        from sqlalchemy import delete
        from hr360.data.engine import make_engine
        from hr360.data.schema import OPS_METADATA, app_settings
        eng = make_engine(request.getfixturevalue("settings").ops_target)
        OPS_METADATA.create_all(eng)
        with eng.begin() as c:
            c.execute(delete(app_settings))
