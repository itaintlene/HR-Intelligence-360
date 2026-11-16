"""Headless Streamlit smoke test (uses the repo data dir; auto-seeds if empty)."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "hr360" / "ui" / "app.py")


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setenv("HR360_EMBEDDINGS", "hash")
    monkeypatch.setenv("HR360_LLM", "none")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("HR360_AS_OF", "2026-11-16")
    return AppTest.from_file(APP, default_timeout=120).run()


def test_app_loads_without_exceptions(app):
    assert not app.exception
    assert len(app.tabs) == 6


def test_policy_question_end_to_end_in_ui(app):
    app.text_area(key="query").set_value("How many sick leave days do I get?").run()
    next(b for b in app.button if b.label == "▶ Run").click().run()
    assert not app.exception
    assert any("COMPLETED" in s.value for s in app.success)
    assert any("Leave Policy" in m.value for m in app.markdown)
