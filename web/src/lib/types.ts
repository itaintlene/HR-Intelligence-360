export type PortalRole = "employee" | "hr" | "pm";

export interface Me {
  subject: string;
  portal_role: PortalRole;
  role: string;
  employee_id: string | null;
  permissions: string[];
}

export interface Finding {
  finding_id: string;
  rule_id: string;
  employee_id: string | null;
  severity: "low" | "medium" | "high" | "critical";
  classification: "confirmed_violation" | "potential_discrepancy";
  title: string;
  evidence: Record<string, unknown>;
  recommendation: string;
}

export interface Citation {
  citation: string;
  doc_file: string;
}

export interface PolicyAnswer {
  answer: string;
  refused: boolean;
  method: string;
  validated: boolean;
  citations: Citation[];
}

export interface Recommendation {
  rec_id: string;
  kind: string;
  employee_id: string | null;
  title: string;
  detail: string;
  items: Record<string, unknown>[];
  priority: "low" | "medium" | "high";
  requires_human_decision: boolean;
}

export interface EmailDraft {
  draft_id: string;
  employee_id: string;
  recipient_masked: string;
  subject: string;
  body: string;
  status: string;
}

export interface AuditSummary {
  total_findings: number;
  employees_affected: number;
  by_severity: Record<string, number>;
  by_classification: Record<string, number>;
  by_rule: Record<string, number>;
  narrative: string;
}

export interface RequestResult {
  request_id: string;
  status: string;
  interrupt: { type: string; request_id: string; drafts?: EmailDraft[] } | null;
  final_response: { status: string; task_type: string; message: string; errors: string[] } | null;
  state: {
    task_type?: string;
    policy_answer?: PolicyAnswer;
    audit_findings?: Finding[];
    audit_summary?: AuditSummary;
    workflow_recommendations?: Recommendation[];
    generated_email_drafts?: EmailDraft[];
    workflow_summary?: string;
    approval_status?: string;
    report_paths?: { pdf: string; csv: string };
    agent_execution_status?: Record<string, { status: string; duration_ms?: number }>;
  };
}

export interface RequestRow {
  request_id: string;
  user_id: string;
  query: string;
  task_type: string | null;
  status: string;
  created_at: string;
}

export interface PendingApproval extends RequestRow {
  drafts: EmailDraft[];
}
