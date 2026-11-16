"""Shared LangGraph state (HRGraphState) and its reducers.

Reducers make every list field idempotent (keyed merge), so a retried/re-executed node can never
duplicate findings, drafts or chunks. Only identifiers, ISO dates and masked values are stored -
raw documents, full national IDs and salary data are never placed in state.
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict


def _keyed(key: str):
    def reducer(old: list[dict] | None, new: list[dict] | None) -> list[dict]:
        merged: dict[Any, dict] = {}
        for item in (old or []) + (new or []):
            merged[item.get(key, id(item))] = item
        return list(merged.values())
    return reducer


def union_list(old: list | None, new: list | None) -> list:
    out = list(old or [])
    for x in new or []:
        if x not in out:
            out.append(x)
    return out


def merge_dict(old: dict | None, new: dict | None) -> dict:
    return {**(old or {}), **(new or {})}


def concat(old: list | None, new: list | None) -> list:
    return list(old or []) + list(new or [])


class HRGraphState(TypedDict, total=False):
    # --- required by spec ---
    request_id: str
    user_query: str
    user_role: str
    task_type: str
    employee_ids: Annotated[list[str], union_list]
    document_metadata: Annotated[list[dict], _keyed("file")]
    extracted_employee_data: Annotated[list[dict], _keyed("source_file")]
    retrieved_policy_chunks: Annotated[list[dict], _keyed("chunk_id")]
    audit_findings: Annotated[list[dict], _keyed("finding_id")]
    workflow_recommendations: Annotated[list[dict], _keyed("rec_id")]
    generated_email_drafts: Annotated[list[dict], _keyed("draft_id")]
    approval_status: str
    agent_execution_status: Annotated[dict, merge_dict]
    errors: Annotated[list[str], concat]
    final_response: dict
    # --- supporting fields ---
    user_id: str
    uploaded_files: list[str]
    policy_query: str
    policy_answer: dict
    audit_summary: dict
    workflow_summary: str
    report_paths: dict
    task_rationale: str
    plan: list[list[str]]       # predefined workflow: ordered stages, each stage = nodes run in parallel
    stage_idx: int
    current_stage: list[str]
    step_count: int
    approval_decision: dict
    project_ids: Annotated[list[str], union_list]
    work_insights: dict
