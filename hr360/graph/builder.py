r"""LangGraph assembly: supervisor hub-and-spoke StateGraph.

START -> supervisor -> dispatch --(conditional: next stage nodes, run in parallel)--> agents -> dispatch ...
                                  \--(no stage left / failure / limit)--> finalize -> END
"""
from __future__ import annotations

import sqlite3

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from hr360.agents.audit_agent import HRAuditAgent
from hr360.agents.base import AgentContext
from hr360.agents.document_agent import DocumentIntelligenceAgent
from hr360.agents.policy_agent import HRPolicyAgent
from hr360.agents.supervisor import AGENT_NODES, SupervisorAgent
from hr360.agents.workflow_agent import HRWorkflowAgent
from hr360.graph.nodes import guarded, make_approval_node, make_report_node
from hr360.graph.state import HRGraphState


def make_checkpointer(path, database_url: str | None = None):
    """Postgres (Neon) checkpointer when a database URL is given, else SQLite; in-memory as a last resort.
    Checkpoints make approval-paused workflows resumable across restarts and serverless invocations."""
    if database_url:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        from hr360.data.engine import normalize_url
        url = normalize_url(database_url).replace("postgresql+psycopg://", "postgresql://", 1)
        pool = ConnectionPool(url, max_size=4, open=True,
                              kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row})
        saver = PostgresSaver(pool)
        saver.setup()
        return saver
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return SqliteSaver(sqlite3.connect(str(path), check_same_thread=False))
    except Exception:  # pragma: no cover
        return MemorySaver()


def build_graph(ctx: AgentContext, checkpointer=None):
    sup = SupervisorAgent(ctx)
    g = StateGraph(HRGraphState)

    g.add_node("supervisor", sup.plan_node)
    g.add_node("dispatch", sup.dispatch_node)
    g.add_node("document_intelligence", guarded("document_intelligence", DocumentIntelligenceAgent(ctx).run, ctx))
    g.add_node("policy", guarded("policy", HRPolicyAgent(ctx).run, ctx))
    g.add_node("audit", guarded("audit", HRAuditAgent(ctx).run, ctx))
    g.add_node("workflow", guarded("workflow", HRWorkflowAgent(ctx).run, ctx))
    g.add_node("report", guarded("report", make_report_node(ctx), ctx))
    g.add_node("approval", make_approval_node(ctx))   # not wrapped: must propagate the interrupt
    g.add_node("finalize", sup.finalize_node)

    g.add_edge(START, "supervisor")
    g.add_edge("supervisor", "dispatch")
    g.add_conditional_edges("dispatch", sup.route, [*AGENT_NODES, "finalize"])
    for n in AGENT_NODES:
        g.add_edge(n, "dispatch")        # every agent reports back to the supervisor hub only
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer or MemorySaver())
