"""Live Postgres (Neon) integration. Skipped unless HR360_RUN_INTEGRATION=1 and DATABASE_URL are set.
Run:  HR360_RUN_INTEGRATION=1 pytest tests/test_postgres_integration.py"""
import os
from datetime import date

import pytest

pytestmark = pytest.mark.skipif(not (os.getenv("HR360_RUN_INTEGRATION") == "1" and os.getenv("DATABASE_URL")),
                                reason="needs HR360_RUN_INTEGRATION=1 and DATABASE_URL")


@pytest.fixture(scope="module")
def runner(tmp_path_factory):
    from hr360.agents.base import AgentContext
    from hr360.config import Settings
    from hr360.data.db import HRDatabase
    from hr360.data.synthetic import build_database
    from hr360.graph.runner import HRRunner
    from hr360.llm.provider import LLMClient

    d = tmp_path_factory.mktemp("pg")
    s = Settings(index_dir=d / "idx", reports_dir=d / "rep", outbox_path=d / "out.jsonl", log_dir=d / "log",
                 embeddings_backend="hash", llm_backend="none", as_of=date(2026, 11, 16))
    assert s.database_url, "DATABASE_URL must be set"
    if not HRDatabase(s.hr_target).has_data():
        build_database(s.hr_target, s.as_of)
    return HRRunner(AgentContext.build(s, llm=LLMClient("none")))


def test_postgres_backed_stack(runner):
    assert runner.ctx.db.engine.dialect.name == "postgresql"
    assert len(runner.ctx.db.employees()) == 36

    r = runner.run("How many sick leave days do I get?", "pg.test", "employee")
    assert r["status"] == "completed" and r["state"]["policy_answer"]["citations"]

    r = runner.run("Give me an audit summary of all employees", "pg.test", "hr_staff")
    assert r["final_response"]["audit_summary"]["total_findings"] == 15

    # approval pause is persisted by the Postgres checkpointer and resumable through a *fresh* runner
    paused = runner.run("Run onboarding for EMP-1035", "pg.test", "hr_staff")
    assert paused["status"] == "awaiting_approval"
    from hr360.graph.runner import HRRunner
    fresh = HRRunner(runner.ctx)
    assert fresh.get(paused["request_id"])["status"] == "awaiting_approval"
    done = fresh.resume(paused["request_id"], "mgr.pg", "hr_manager", False, "integration test: reject")
    assert done["status"] == "completed" and done["state"]["approval_status"] == "rejected"
    actions = {e["action"] for e in runner.ctx.audit_log.fetch(paused["request_id"])}
    assert {"request_received", "approval_rejected", "request_completed"} <= actions
