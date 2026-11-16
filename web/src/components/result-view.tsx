import { Link } from "@tanstack/react-router";
import { Download, FileText, ShieldAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { useApi } from "@/lib/api";
import type { Finding, RequestResult } from "@/lib/types";

export function FindingsTable({ findings }: { findings: Finding[] }) {
  return (
    <Table>
      <THead>
        <TR>
          <TH>Employee</TH>
          <TH>Severity</TH>
          <TH>Type</TH>
          <TH>Finding</TH>
          <TH>Recommendation</TH>
        </TR>
      </THead>
      <TBody>
        {findings.map((f) => (
          <TR key={f.finding_id}>
            <TD className="font-mono text-xs">{f.employee_id ?? "—"}</TD>
            <TD>
              <Badge variant={f.severity}>{f.severity}</Badge>
            </TD>
            <TD>
              <Badge variant={f.classification === "confirmed_violation" ? "danger" : "warning"}>
                {f.classification === "confirmed_violation" ? "Confirmed" : "Potential"}
              </Badge>
            </TD>
            <TD>
              <div>{f.title}</div>
              <div className="font-mono text-[11px] text-muted-foreground">{f.rule_id}</div>
            </TD>
            <TD className="text-muted-foreground">{f.recommendation}</TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

export function ReportButtons({ requestId }: { requestId: string }) {
  const { download } = useApi();
  return (
    <div className="flex gap-2">
      <Button variant="outline" size="sm" onClick={() => download(`/api/requests/${requestId}/report/pdf`, `${requestId}_report.pdf`)}>
        <Download className="size-4" /> PDF report
      </Button>
      <Button variant="outline" size="sm" onClick={() => download(`/api/requests/${requestId}/report/csv`, `${requestId}_findings.csv`)}>
        <Download className="size-4" /> CSV
      </Button>
    </div>
  );
}

export function ResultView({ result }: { result: RequestResult }) {
  const { state, final_response: fr } = result;
  const tone = fr?.status === "completed" ? "success" : fr?.status === "denied" || fr?.status === "partial" ? "danger" : "warning";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant={result.status === "awaiting_approval" ? "warning" : tone}>{result.status.replace("_", " ")}</Badge>
        {fr && <span className="text-muted-foreground">workflow: {fr.task_type}</span>}
        <span className="font-mono text-xs text-muted-foreground">{result.request_id}</span>
      </div>

      {result.status === "awaiting_approval" && (
        <Card className="border-amber-300 bg-amber-50">
          <CardContent className="flex items-center gap-3 pt-5 text-sm">
            <ShieldAlert className="size-5 text-amber-700" />
            <span>
              {result.interrupt?.drafts?.length ?? 0} email draft(s) wait for human approval. Nothing is sent until an authorised approver
              signs off.
            </span>
            <Button asChild size="sm" variant="outline" className="ml-auto">
              <Link to="/app/approvals">Open approvals</Link>
            </Button>
          </CardContent>
        </Card>
      )}

      {fr?.message && (
        <Card>
          <CardContent className="pt-5 text-sm leading-relaxed">{fr.message}</CardContent>
        </Card>
      )}

      {state.policy_answer?.citations && state.policy_answer.citations.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileText className="size-4" /> Sources
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            {state.policy_answer.citations.map((c) => (
              <div key={c.citation}>
                {c.citation} <span className="text-xs text-muted-foreground">({c.doc_file})</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {state.audit_summary && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[
            ["Findings", state.audit_summary.total_findings],
            ["Employees affected", state.audit_summary.employees_affected],
            ["Confirmed", state.audit_summary.by_classification.confirmed_violation ?? 0],
            ["Potential", state.audit_summary.by_classification.potential_discrepancy ?? 0],
          ].map(([label, value]) => (
            <Card key={label as string}>
              <CardContent className="pt-5">
                <div className="text-2xl font-semibold">{value}</div>
                <div className="text-xs text-muted-foreground">{label}</div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {state.audit_findings && state.audit_findings.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold">Audit findings</h3>
          <FindingsTable findings={state.audit_findings} />
        </div>
      )}

      {state.workflow_recommendations && state.workflow_recommendations.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold">Recommendations</h3>
          <div className="space-y-2">
            {state.workflow_recommendations.map((r) => (
              <Card key={r.rec_id}>
                <CardContent className="space-y-2 pt-5 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={r.priority === "high" ? "high" : r.priority === "medium" ? "medium" : "low"}>{r.priority}</Badge>
                    {r.requires_human_decision && <Badge variant="outline">needs human decision</Badge>}
                    <span className="font-medium">{r.title}</span>
                  </div>
                  {r.detail && <p className="text-muted-foreground">{r.detail}</p>}
                  {r.kind === "checklist" && (
                    <ul className="grid gap-1 md:grid-cols-2">
                      {r.items.map((i) => (
                        <li key={String(i.item)} className="flex items-center gap-2">
                          <span>{i.status === "done" ? "✅" : "⬜"}</span>
                          {String(i.item)}
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {state.report_paths && <ReportButtons requestId={result.request_id} />}

      {fr?.errors && fr.errors.length > 0 && (
        <Card className="border-red-200">
          <CardContent className="pt-5 text-xs text-red-700">{fr.errors.join(" · ")}</CardContent>
        </Card>
      )}
    </div>
  );
}
