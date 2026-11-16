import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { AskPanel } from "@/components/ask-panel";
import { PageHeader } from "@/components/layout";
import { ResultView } from "@/components/result-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/form";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { useApi } from "@/lib/api";
import type { Me, PendingApproval, RequestResult, RequestRow } from "@/lib/types";

export function AskPage() {
  return (
    <>
      <PageHeader title="Ask HR" description="Answers come only from the company's HR policy documents and always cite their source." />
      <AskPanel
        placeholder="e.g. How many days of earned leave can I carry forward?"
        examples={["How many sick leave days do I get?", "What is the remote work policy?", "What documents do new joiners submit?"]}
      />
    </>
  );
}

export function WorkflowsPage() {
  return (
    <>
      <PageHeader title="Workflows" description="Document audit, onboarding automation and compliance summaries. Consequential actions need approval." />
      <AskPanel
        allowUpload
        placeholder="e.g. Audit the attached documents · Run onboarding for EMP-1031 and EMP-1035"
        examples={["Audit the attached documents", "Run onboarding for EMP-1031, EMP-1032 and EMP-1035", "Which employees have expired documents?"]}
      />
    </>
  );
}

export function TeamLeavePage({ me }: { me: Me }) {
  return (
    <>
      <PageHeader
        title={me.portal_role === "pm" ? "Team leave" : "Leave requests"}
        description={
          me.portal_role === "pm"
            ? "Pending leave requests from your direct reports, with policy flags. The system never approves leave — you decide."
            : "Pending leave requests with policy flags, prepared for the reporting manager's decision."
        }
      />
      <AskPanel placeholder="Summarize pending leave requests" examples={["Summarize pending leave requests"]} />
    </>
  );
}

export function DashboardPage() {
  const { raw } = useApi();
  const qc = useQueryClient();
  const run = useMutation({
    mutationFn: async () => {
      const body = new FormData();
      body.set("query", "Give me an audit summary of all employee records");
      return (await raw("/api/requests", { method: "POST", body })).json() as Promise<RequestResult>;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["requests"] }),
  });
  const s = run.data?.state.audit_summary;
  return (
    <>
      <PageHeader title="Audit dashboard" description="Deterministic rules-engine results over all employee records. Findings are never decided by the LLM." />
      <Button onClick={() => run.mutate()} disabled={run.isPending} className="mb-6">
        {run.isPending && <Loader2 className="size-4 animate-spin" />} Run full audit
      </Button>
      {run.isError && <p className="text-sm text-destructive">{(run.error as Error).message}</p>}
      {s && (
        <div className="mb-6 grid gap-4 md:grid-cols-2">
          <Card>
            <CardContent className="space-y-2 pt-5">
              <h3 className="text-sm font-semibold">By severity</h3>
              {["critical", "high", "medium", "low"].map((k) => (
                <Bar key={k} label={k} value={s.by_severity[k] ?? 0} max={s.total_findings} />
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardContent className="space-y-2 pt-5">
              <h3 className="text-sm font-semibold">By rule</h3>
              {Object.entries(s.by_rule).map(([k, v]) => (
                <Bar key={k} label={k.replace(/^R\d+_/, "").toLowerCase()} value={v} max={s.total_findings} />
              ))}
            </CardContent>
          </Card>
          <Card className="md:col-span-2">
            <CardContent className="pt-5 text-sm">{s.narrative}</CardContent>
          </Card>
        </div>
      )}
      {run.data && <ResultView result={run.data} />}
    </>
  );
}

function Bar({ label, value, max }: { label: string; value: number; max: number }) {
  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="w-40 shrink-0 truncate capitalize text-muted-foreground">{label}</span>
      <div className="h-2 flex-1 rounded-full bg-muted">
        <div className="h-2 rounded-full bg-primary" style={{ width: `${max ? (value / max) * 100 : 0}%` }} />
      </div>
      <span className="w-6 text-right tabular-nums">{value}</span>
    </div>
  );
}

export function RequestsPage() {
  const { json } = useApi();
  const [open, setOpen] = useState<string | null>(null);
  const list = useQuery({ queryKey: ["requests"], queryFn: () => json<RequestRow[]>("/api/requests") });
  const detail = useQuery({ queryKey: ["request", open], enabled: !!open, queryFn: () => json<RequestResult>(`/api/requests/${open}`) });
  return (
    <>
      <PageHeader title="Requests" description="History of requests you are allowed to see." />
      {list.isLoading ? (
        <Loader2 className="size-5 animate-spin" />
      ) : (
        <Table>
          <THead>
            <TR>
              <TH>When</TH>
              <TH>Request</TH>
              <TH>Workflow</TH>
              <TH>Status</TH>
            </TR>
          </THead>
          <TBody>
            {(list.data ?? []).map((r) => (
              <TR key={r.request_id} className="cursor-pointer" onClick={() => setOpen(r.request_id)}>
                <TD className="whitespace-nowrap text-xs text-muted-foreground">{r.created_at.replace("T", " ").slice(0, 16)}</TD>
                <TD>{r.query}</TD>
                <TD>{r.task_type ?? "—"}</TD>
                <TD>
                  <Badge variant={r.status === "completed" ? "success" : r.status === "awaiting_approval" ? "warning" : "secondary"}>
                    {r.status.replace("_", " ")}
                  </Badge>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      {open && (
        <div className="mt-6">{detail.isLoading ? <Loader2 className="size-5 animate-spin" /> : detail.data && <ResultView result={detail.data} />}</div>
      )}
    </>
  );
}

export function ApprovalsPage({ me }: { me: Me }) {
  const { json, postJson } = useApi();
  const qc = useQueryClient();
  const canApprove = me.permissions.includes("approve_actions");
  const pending = useQuery({ queryKey: ["approvals"], queryFn: () => json<PendingApproval[]>("/api/approvals") });
  const [picked, setPicked] = useState<Record<string, Set<string>>>({});
  const [comment, setComment] = useState("");
  const decide = useMutation({
    mutationFn: ({ id, approved, ids }: { id: string; approved: boolean; ids?: string[] }) =>
      postJson(`/api/requests/${id}/decision`, { approved, comment, approved_draft_ids: ids }),
    onSuccess: () => {
      setComment("");
      qc.invalidateQueries({ queryKey: ["approvals"] });
      qc.invalidateQueries({ queryKey: ["requests"] });
    },
  });
  const selected = (a: PendingApproval) => picked[a.request_id] ?? new Set(a.drafts.map((d) => d.draft_id));
  return (
    <>
      <PageHeader title="Approvals" description="Human-in-the-loop: nothing is sent until an authorised approver approves." />
      {!canApprove && (
        <p className="mb-4 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm">You can review drafts, but only HR managers can approve or reject them.</p>
      )}
      {pending.data?.length === 0 && <p className="text-sm text-muted-foreground">Nothing is waiting for approval.</p>}
      <div className="space-y-4">
        {pending.data?.map((a) => (
          <Card key={a.request_id}>
            <CardContent className="space-y-4 pt-5">
              <div className="text-sm">
                <span className="font-mono text-xs">{a.request_id}</span> · requested by <b>{a.user_id}</b> · <i>{a.query}</i>
              </div>
              {a.drafts.map((d) => (
                <div key={d.draft_id} className="rounded-md border p-3">
                  <label className="flex items-center gap-2 text-sm font-medium">
                    <input
                      type="checkbox"
                      disabled={!canApprove}
                      checked={selected(a).has(d.draft_id)}
                      onChange={(e) => {
                        const next = new Set(selected(a));
                        if (e.target.checked) next.add(d.draft_id);
                        else next.delete(d.draft_id);
                        setPicked({ ...picked, [a.request_id]: next });
                      }}
                    />
                    {d.subject} <span className="font-normal text-muted-foreground">→ {d.employee_id} ({d.recipient_masked})</span>
                  </label>
                  <pre className="mt-2 whitespace-pre-wrap rounded bg-muted p-3 text-xs">{d.body}</pre>
                </div>
              ))}
              {canApprove && (
                <div className="flex flex-wrap items-center gap-2">
                  <Input className="max-w-xs" placeholder="Comment (optional)" value={comment} onChange={(e) => setComment(e.target.value)} />
                  <Button disabled={decide.isPending} onClick={() => decide.mutate({ id: a.request_id, approved: true, ids: [...selected(a)] })}>
                    Approve selected
                  </Button>
                  <Button variant="destructive" disabled={decide.isPending} onClick={() => decide.mutate({ id: a.request_id, approved: false })}>
                    Reject all
                  </Button>
                </div>
              )}
              {decide.isError && <p className="text-sm text-destructive">{(decide.error as Error).message}</p>}
            </CardContent>
          </Card>
        ))}
      </div>
    </>
  );
}

export function EmployeesPage() {
  const { json } = useApi();
  const q = useQuery({ queryKey: ["employees"], queryFn: () => json<{ full: boolean; rows: Record<string, string>[] }>("/api/employees") });
  const cols = q.data?.rows[0] ? Object.keys(q.data.rows[0]) : [];
  return (
    <>
      <PageHeader title="Employees" description={q.data?.full ? "Full records (HR manager)." : "Sensitive fields are masked or hidden for your role."} />
      {q.isLoading ? (
        <Loader2 className="size-5 animate-spin" />
      ) : (
        <Table>
          <THead>
            <TR>
              {cols.map((c) => (
                <TH key={c}>{c.replace("_", " ")}</TH>
              ))}
            </TR>
          </THead>
          <TBody>
            {q.data?.rows.map((r) => (
              <TR key={r.employee_id}>
                {cols.map((c) => (
                  <TD key={c} className="whitespace-nowrap text-xs">
                    {r[c]}
                  </TD>
                ))}
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </>
  );
}

export function AuditLogPage() {
  const { json } = useApi();
  const q = useQuery({ queryKey: ["audit-log"], queryFn: () => json<Record<string, string>[]>("/api/audit-log") });
  return (
    <>
      <PageHeader title="Audit log" description="Append-only record of agent runs, denials and approvals." />
      <Table>
        <THead>
          <TR>
            {["ts", "request_id", "actor", "role", "agent", "action", "detail"].map((c) => (
              <TH key={c}>{c}</TH>
            ))}
          </TR>
        </THead>
        <TBody>
          {q.data?.map((r) => (
            <TR key={String(r.id)}>
              {["ts", "request_id", "actor", "role", "agent", "action", "detail"].map((c) => (
                <TD key={c} className="max-w-xs truncate text-xs">
                  {r[c]}
                </TD>
              ))}
            </TR>
          ))}
        </TBody>
      </Table>
    </>
  );
}
