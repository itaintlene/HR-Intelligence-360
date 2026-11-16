"""Shared Pydantic models (structured outputs exchanged between agents)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]
Classification = Literal["confirmed_violation", "potential_discrepancy"]
SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

TaskType = Literal["policy_question", "document_audit", "onboarding", "audit_summary", "leave_summary", "project_status", "person_record",
                   "unsupported"]


class Finding(BaseModel):
    finding_id: str
    rule_id: str
    employee_id: str | None = None
    severity: Severity
    classification: Classification
    title: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    recommendation: str = ""
    explanation: str | None = None  # LLM-written narrative only; never affects classification


class ExtractedEmployeeRecord(BaseModel):
    source_file: str
    document_type: str = "unknown"
    document_type_confidence: float = 0.0
    employee_id: str | None = None
    department: str | None = None
    designation: str | None = None
    joining_date: str | None = None      # ISO date
    issue_date: str | None = None
    expiry_date: str | None = None
    national_id_masked: str | None = None
    field_confidence: dict[str, float] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    low_confidence_fields: list[str] = Field(default_factory=list)
    ocr_used: bool = False
    page_count: int = 0
    injection_flags: list[str] = Field(default_factory=list)


class TaskClassification(BaseModel):
    task_type: TaskType
    rationale: str = ""


class EmailDraft(BaseModel):
    draft_id: str
    employee_id: str
    recipient_masked: str
    subject: str
    body: str
    purpose: str = "missing_documents"
    status: Literal["draft", "approved", "rejected", "queued", "sent", "failed"] = "draft"
    requires_approval: bool = True


class WorkflowRecommendation(BaseModel):
    rec_id: str
    kind: Literal["checklist", "task", "leave_summary", "summary"]
    employee_id: str | None = None
    title: str
    detail: str = ""
    items: list[dict[str, Any]] = Field(default_factory=list)
    priority: Literal["low", "medium", "high"] = "medium"
    requires_human_decision: bool = False
