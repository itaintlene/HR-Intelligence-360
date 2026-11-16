import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ExternalLink, Loader2, Paperclip, ShieldQuestion } from "lucide-react";
import { useRef, useState } from "react";
import { PageHeader } from "@/components/layout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, Textarea } from "@/components/ui/form";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { useApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Me } from "@/lib/types";

/* ------------------------------------------------------------------ types */
interface Evidence {
  evidence_id: string; filename: string; description: string; ai_summary: string; analysis_method: string;
  review_status: "pending" | "verified" | "disputed"; reviewed_by: string | null; injection_flags: string[];
}
interface TimelineEntry {
  standup_id: string; date: string; done: string; planned: string; blockers: string; blocker_status: string;
  self_progress: number | null; hours: number | null; evidence: Evidence[];
}
interface Flag { type: string; severity: "info" | "watch" | "attention"; employee_id: string | null; message: string }
interface PersonProject {
  project: { project_id: string; name: string; repo: string | null };
  stats: { days_submitted: number; days_expected: number; submission_rate: number | null; carryover_rate: number | null };
  open_blocker: { text: string; age_days: number } | null;
  github: { commits: number; prs_opened: number; prs_merged: number; reviews: number; events: number; raw_lines_added: number; raw_lines_removed: number; note: string;
            recent: { event_type: string; title: string; url: string | null; event_ts: string }[] };
  evidence_count: number; evidence_unreviewed: number; timeline: TimelineEntry[]; flags: Flag[];
}
interface PersonRecord { employee_id: string; window: { working_days: number; from: string; to: string }; projects: PersonProject[]; flags: Flag[]; disclaimer: string }
interface ProjectRow {
  project_id: string; name: string; description: string; manager_employee_id: string; target_date: string; status: string; i_manage: boolean; i_am_member: boolean;
  progress?: { pct_complete: number | null; expected_pct: number; schedule_status: string }; open_blockers?: number; flags?: number; members?: number;
}
interface ProjectDetail {
  project: { project_id: string; name: string; manager_employee_id: string; target_date: string; repo: string | null };
  progress: { pct_complete: number | null; expected_pct: number; delta: number | null; schedule_status: string };
  milestones: { milestone_id: string; name: string; due_date: string; status: string; overdue: boolean }[];
  blockers: { employee_id: string; text: string; first_seen: string; age_days: number }[];
  members: { employee_id: string; role: string; submission_rate: number | null; days_submitted: number; days_expected: number; last_update: string | null;
             quiet: boolean; open_blocker: boolean; carryover_rate: number | null; github: { commits: number; prs_merged: number; reviews: number; events: number } }[];
  flags: Flag[]; github: { current: { events: number }; previous: { events: number } }; window: { working_days: number; from: string; to: string }; disclaimer: string;
}

const SCHEDULE: Record<string, { label: string; variant: "success" | "warning" | "danger" | "secondary" }> = {
  on_track: { label: "On track", variant: "success" }, at_risk: { label: "At risk", variant: "warning" },
  behind: { label: "Behind", variant: "danger" }, done: { label: "Done", variant: "secondary" },
};
const FLAG_STYLE: Record<string, string> = { attention: "border-amber-300 bg-amber-50", watch: "border-sky-200 bg-sky-50", info: "border-border bg-muted/40" };
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);

function Disclaimer({ text }: { text?: string }) {
  return (
    <p className="flex items-start gap-2 rounded-md border bg-muted/40 p-3 text-xs text-muted-foreground">
      <ShieldQuestion className="mt-0.5 size-4 shrink-0" />
      {text ?? "Signals for human review, not a performance rating. No score or ranking is computed."}
    </p>
  );
}

function FlagList({ flags }: { flags: Flag[] }) {
  if (!flags.length) return <p className="text-sm text-muted-foreground">No signals raised.</p>;
  return (
    <ul className="space-y-2">
      {flags.map((f, i) => (
        <li key={i} className={cn("flex items-start gap-2 rounded-md border p-2 text-sm", FLAG_STYLE[f.severity])}>
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-700" />
          <span>
            {f.employee_id && <span className="mr-1 font-mono text-xs">{f.employee_id}</span>}
            {f.message} <span className="text-xs text-muted-foreground">({f.type.replace(/_/g, " ")})</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/* ------------------------------------------------------------------ evidence + record */
function EvidenceItem({ ev, canReview }: { ev: Evidence; canReview: boolean }) {
  const { sendJson } = useApi();
  const qc = useQueryClient();
  const review = useMutation({
    mutationFn: (status: string) => sendJson("PATCH", `/api/work/evidence/${ev.evidence_id}/review`, { status }),
    onSuccess: () => qc.invalidateQueries(),
  });
  const tone = ev.review_status === "verified" ? "success" : ev.review_status === "disputed" ? "danger" : "warning";
  return (
    <div className="rounded-md border bg-card p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Paperclip className="size-4 text-muted-foreground" />
        <span className="font-medium">{ev.filename}</span>
        <Badge variant={tone}>{ev.review_status === "pending" ? "awaiting human review" : ev.review_status}</Badge>
        <Badge variant="outline">AI summary · {ev.analysis_method}</Badge>
        {ev.injection_flags.length > 0 && <Badge variant="danger">{ev.injection_flags.length} suspicious instruction line(s) removed</Badge>}
      </div>
      {ev.description && <p className="mt-1 text-xs text-muted-foreground">Employee note: {ev.description}</p>}
      <p className="mt-2">{ev.ai_summary}</p>
      {canReview && ev.review_status === "pending" && (
        <div className="mt-2 flex gap-2">
          <Button size="sm" variant="outline" disabled={review.isPending} onClick={() => review.mutate("verified")}>
            <CheckCircle2 className="size-4" /> Mark verified
          </Button>
          <Button size="sm" variant="ghost" disabled={review.isPending} onClick={() => review.mutate("disputed")}>
            Dispute
          </Button>
        </div>
      )}
      {review.isError && <p className="mt-1 text-xs text-destructive">{(review.error as Error).message}</p>}
    </div>
  );
}

export function PersonRecordView({ rec, canReview }: { rec: PersonRecord; canReview: boolean }) {
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-semibold">
          Work record · <span className="font-mono">{rec.employee_id}</span>
        </h2>
        <Badge variant="secondary">
          {rec.window.from} → {rec.window.to} ({rec.window.working_days} working days)
        </Badge>
      </div>
      <Disclaimer text={rec.disclaimer} />
      {rec.projects.length === 0 && <p className="text-sm text-muted-foreground">Not a member of any project yet.</p>}
      {rec.projects.map((p) => (
        <Card key={p.project.project_id}>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2">
              {p.project.name} <span className="font-mono text-xs font-normal text-muted-foreground">{p.project.project_id}</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {[
                ["Stand-ups", `${p.stats.days_submitted}/${p.stats.days_expected}`],
                ["Consistency", pct(p.stats.submission_rate)],
                ["PRs merged / reviews", `${p.github.prs_merged} / ${p.github.reviews}`],
                ["Proof files", `${p.evidence_count} (${p.evidence_unreviewed} unreviewed)`],
              ].map(([k, v]) => (
                <div key={k} className="rounded-md border p-3">
                  <div className="text-lg font-semibold">{v}</div>
                  <div className="text-xs text-muted-foreground">{k}</div>
                </div>
              ))}
            </div>
            {p.open_blocker && (
              <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm">
                <b>Open blocker · {p.open_blocker.age_days} days:</b> {p.open_blocker.text}
              </div>
            )}
            <FlagList flags={p.flags} />
            {p.github.recent.length > 0 && (
              <div>
                <h4 className="mb-1 text-sm font-semibold">Recent GitHub activity</h4>
                <ul className="space-y-1 text-sm">
                  {p.github.recent.slice(0, 6).map((e, i) => (
                    <li key={i} className="flex items-center gap-2">
                      <Badge variant="outline">{e.event_type.replace("_", " ")}</Badge>
                      <span className="truncate">{e.title}</span>
                      <span className="text-xs text-muted-foreground">{e.event_ts.slice(0, 10)}</span>
                      {e.url && (
                        <a href={e.url} target="_blank" rel="noreferrer" className="text-primary">
                          <ExternalLink className="size-3" />
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
                <p className="mt-1 text-xs text-muted-foreground">
                  Raw context: +{p.github.raw_lines_added} / −{p.github.raw_lines_removed} lines. {p.github.note}
                </p>
              </div>
            )}
            <div>
              <h4 className="mb-2 text-sm font-semibold">Stand-up timeline</h4>
              <div className="space-y-2">
                {p.timeline.slice(0, 12).map((t) => (
                  <div key={t.standup_id} className="rounded-md border p-3 text-sm">
                    <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <span className="font-mono">{t.date}</span>
                      {t.hours !== null && <span>{t.hours}h</span>}
                      {t.self_progress !== null && <span>self-reported {t.self_progress}%</span>}
                      {t.blockers && <Badge variant={t.blocker_status === "open" ? "warning" : "secondary"}>blocker {t.blocker_status}</Badge>}
                    </div>
                    {t.done && <p><b>Done:</b> {t.done}</p>}
                    {t.planned && <p><b>Plan:</b> {t.planned}</p>}
                    {t.blockers && <p className="text-amber-800"><b>Blocker:</b> {t.blockers}</p>}
                    {t.evidence.length > 0 && (
                      <div className="mt-2 space-y-2">
                        {t.evidence.map((e) => (
                          <EvidenceItem key={e.evidence_id} ev={e} canReview={canReview} />
                        ))}
                      </div>
                    )}
                  </div>
                ))}
                {p.timeline.length === 0 && <p className="text-sm text-muted-foreground">No stand-ups in this window.</p>}
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ stand-up form */
export function StandupPage() {
  const { json, raw } = useApi();
  const qc = useQueryClient();
  const projects = useQuery({ queryKey: ["work-projects"], queryFn: () => json<ProjectRow[]>("/api/work/projects") });
  const mine = (projects.data ?? []).filter((p) => p.i_am_member);
  const [form, setForm] = useState({ project_id: "", done_text: "", planned_text: "", blockers_text: "", blocker_status: "open", self_progress: "", hours: "" });
  const [saved, setSaved] = useState<{ standup_id: string; entry_date: string } | null>(null);
  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }));
  const projectId = form.project_id || mine[0]?.project_id || "";

  const submit = useMutation({
    mutationFn: () =>
      json<{ standup_id: string; entry_date: string }>("/api/work/standups", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId, done_text: form.done_text, planned_text: form.planned_text, blockers_text: form.blockers_text,
          blocker_status: form.blockers_text.trim() ? form.blocker_status : "none",
          self_progress: form.self_progress === "" ? null : Number(form.self_progress), hours: form.hours === "" ? null : Number(form.hours),
        }),
      }),
    onSuccess: (r) => { setSaved(r); qc.invalidateQueries({ queryKey: ["my-work"] }); },
  });

  const fileRef = useRef<HTMLInputElement>(null);
  const [note, setNote] = useState("");
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.set("file", file);
      body.set("description", note);
      return (await raw(`/api/work/standups/${saved!.standup_id}/evidence`, { method: "POST", body })).json() as Promise<{ ai_summary: string; analysis_method: string; injection_flags: string[] }>;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["my-work"] }),
  });

  return (
    <>
      <PageHeader title="Daily stand-up" description="What you did, what you're doing next, and anything blocking you. Your manager and HR can see this record, and so can you." />
      {projects.isLoading ? <Loader2 className="size-5 animate-spin" /> : mine.length === 0 ? (
        <Card><CardContent className="pt-5 text-sm">You are not a member of any project yet. Ask your project manager or HR to add you.</CardContent></Card>
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardContent className="space-y-4 pt-5">
              <div className="space-y-1">
                <Label htmlFor="proj">Project</Label>
                <select id="proj" className="h-9 w-full rounded-md border border-input bg-card px-2 text-sm" value={projectId} onChange={(e) => { set("project_id", e.target.value); setSaved(null); }}>
                  {mine.map((p) => <option key={p.project_id} value={p.project_id}>{p.name} ({p.project_id})</option>)}
                </select>
              </div>
              <div className="space-y-1"><Label>What did you work on since the last update?</Label>
                <Textarea value={form.done_text} onChange={(e) => set("done_text", e.target.value)} placeholder="Finished the retry logic for payment webhooks (PR #482)…" /></div>
              <div className="space-y-1"><Label>What will you work on next?</Label>
                <Textarea value={form.planned_text} onChange={(e) => set("planned_text", e.target.value)} placeholder="Add integration tests, start on refund flow…" /></div>
              <div className="space-y-1"><Label>Blockers (optional)</Label>
                <Textarea className="min-h-16" value={form.blockers_text} onChange={(e) => set("blockers_text", e.target.value)} placeholder="Waiting for vendor API credentials…" />
                {form.blockers_text.trim() && (
                  <select className="mt-1 h-9 rounded-md border border-input bg-card px-2 text-sm" value={form.blocker_status} onChange={(e) => set("blocker_status", e.target.value)}>
                    <option value="open">Still blocked</option><option value="resolved">Resolved</option>
                  </select>
                )}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1"><Label>Hours worked</Label><Input type="number" min={0} max={24} step={0.5} value={form.hours} onChange={(e) => set("hours", e.target.value)} /></div>
                <div className="space-y-1"><Label>Your progress estimate (%)</Label><Input type="number" min={0} max={100} value={form.self_progress} onChange={(e) => set("self_progress", e.target.value)} /></div>
              </div>
              {submit.isError && <p className="text-sm text-destructive">{(submit.error as Error).message}</p>}
              <Button disabled={submit.isPending || (!form.done_text.trim() && !form.planned_text.trim())} onClick={() => submit.mutate()}>
                {submit.isPending && <Loader2 className="size-4 animate-spin" />} Submit stand-up
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Proof of work</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-sm">
              {!saved ? <p className="text-muted-foreground">Submit your stand-up first, then attach screenshots, reports or documents as proof. An AI reads them and writes a short summary; your manager or HR confirms it.</p> : (
                <>
                  <p className="flex items-center gap-2 text-emerald-700"><CheckCircle2 className="size-4" /> Saved for {saved.entry_date}. Attach proof (optional):</p>
                  <Input placeholder="What does this file show? (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
                  <input ref={fileRef} type="file" hidden accept=".pdf,.docx,.png,.jpg,.jpeg,.txt,.md,.csv" onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} />
                  <Button variant="outline" disabled={upload.isPending} onClick={() => fileRef.current?.click()}>
                    {upload.isPending ? <Loader2 className="size-4 animate-spin" /> : <Paperclip className="size-4" />} Upload proof
                  </Button>
                  {upload.isError && <p className="text-destructive">{(upload.error as Error).message}</p>}
                  {upload.data && (
                    <div className="rounded-md border bg-muted/40 p-3">
                      <div className="mb-1 flex gap-2"><Badge variant="outline">AI summary · {upload.data.analysis_method}</Badge><Badge variant="warning">awaiting human review</Badge></div>
                      {upload.data.ai_summary}
                      {upload.data.injection_flags.length > 0 && <p className="mt-1 text-xs text-destructive">{upload.data.injection_flags.length} instruction-like line(s) in the file were ignored.</p>}
                    </div>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </>
  );
}

export function MyWorkPage() {
  const { json } = useApi();
  const q = useQuery({ queryKey: ["my-work"], queryFn: () => json<PersonRecord>("/api/work/me") });
  return (
    <>
      <PageHeader title="My work record" description="Exactly what your manager and HR can see about your stand-ups, proof and GitHub activity." />
      {q.isLoading && <Loader2 className="size-5 animate-spin" />}
      {q.isError && <p className="text-sm text-destructive">{(q.error as Error).message}</p>}
      {q.data && <PersonRecordView rec={q.data} canReview={false} />}
    </>
  );
}

/* ------------------------------------------------------------------ projects (PM + HR) */
export function ProjectsPage({ me }: { me: Me }) {
  const { json, raw, sendJson } = useApi();
  const qc = useQueryClient();
  const [sel, setSel] = useState<string | null>(null);
  const [person, setPerson] = useState<string | null>(null);
  const list = useQuery({ queryKey: ["work-projects"], queryFn: () => json<ProjectRow[]>("/api/work/projects") });
  const rows = (list.data ?? []).filter((p) => p.progress);
  const detail = useQuery({ queryKey: ["project", sel], enabled: !!sel, queryFn: () => json<ProjectDetail>(`/api/work/projects/${sel}`) });
  const rec = useQuery({ queryKey: ["project-person", sel, person], enabled: !!sel && !!person, queryFn: () => json<PersonRecord>(`/api/work/projects/${sel}/people/${person}`) });
  const narrative = useMutation({
    mutationFn: async () => {
      const body = new FormData();
      body.set("query", `What is the status of project ${sel}?`);
      return (await raw("/api/requests", { method: "POST", body })).json() as Promise<{ final_response: { message: string } }>;
    },
  });
  const milestone = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => sendJson("PATCH", `/api/work/milestones/${id}`, { status }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["project", sel] }); qc.invalidateQueries({ queryKey: ["work-projects"] }); },
  });
  const d = detail.data;
  const canEditMilestones = me.permissions.includes("manage_projects") || me.portal_role === "pm";

  return (
    <>
      <PageHeader title="Projects" description="Progress against milestones, open blockers and stand-up activity. People are listed alphabetically — never ranked." />
      {list.isLoading && <Loader2 className="size-5 animate-spin" />}
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {rows.map((p) => {
          const s = SCHEDULE[p.progress!.schedule_status];
          return (
            <button key={p.project_id} onClick={() => { setSel(p.project_id); setPerson(null); narrative.reset(); }} className="text-left">
              <Card className={cn("h-full transition hover:border-primary", sel === p.project_id && "border-primary ring-1 ring-primary")}>
                <CardContent className="space-y-3 pt-5">
                  <div className="flex items-start justify-between gap-2">
                    <div><div className="font-semibold">{p.name}</div><div className="font-mono text-xs text-muted-foreground">{p.project_id}</div></div>
                    <Badge variant={s.variant}>{s.label}</Badge>
                  </div>
                  <div>
                    <div className="relative h-2 rounded-full bg-muted">
                      <div className="h-2 rounded-full bg-primary" style={{ width: `${p.progress!.pct_complete ?? 0}%` }} />
                      <div className="absolute -top-1 h-4 w-0.5 bg-foreground/60" style={{ left: `${p.progress!.expected_pct}%` }} title="Expected by timeline" />
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">{p.progress!.pct_complete ?? 0}% done · {p.progress!.expected_pct}% expected · due {p.target_date}</div>
                  </div>
                  <div className="flex gap-2 text-xs">
                    <Badge variant={p.open_blockers ? "warning" : "secondary"}>{p.open_blockers} blocker(s)</Badge>
                    <Badge variant={p.flags ? "warning" : "secondary"}>{p.flags} signal(s)</Badge>
                    <Badge variant="outline">{p.members} members</Badge>
                  </div>
                </CardContent>
              </Card>
            </button>
          );
        })}
      </div>
      {!list.isLoading && rows.length === 0 && <p className="text-sm text-muted-foreground">No projects to show.</p>}

      {sel && (
        <div className="mt-8 space-y-6">
          {detail.isLoading && <Loader2 className="size-5 animate-spin" />}
          {d && (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="text-xl font-semibold">{d.project.name}</h2>
                <Badge variant={SCHEDULE[d.progress.schedule_status].variant}>{SCHEDULE[d.progress.schedule_status].label}</Badge>
                <span className="text-sm text-muted-foreground">window {d.window.from} → {d.window.to} · GitHub events {d.github.current.events} (previous period {d.github.previous.events})</span>
                <Button className="ml-auto" size="sm" variant="outline" disabled={narrative.isPending} onClick={() => narrative.mutate()}>
                  {narrative.isPending && <Loader2 className="size-4 animate-spin" />} Ask the agent for a summary
                </Button>
              </div>
              {narrative.data && <Card><CardContent className="pt-5 text-sm leading-relaxed">{narrative.data.final_response.message}</CardContent></Card>}
              <Disclaimer text={d.disclaimer} />
              <div className="grid gap-6 lg:grid-cols-2">
                <div className="space-y-2">
                  <h3 className="text-sm font-semibold">Signals</h3>
                  <FlagList flags={d.flags} />
                </div>
                <div className="space-y-2">
                  <h3 className="text-sm font-semibold">Open blockers</h3>
                  {d.blockers.length === 0 ? <p className="text-sm text-muted-foreground">None.</p> : d.blockers.map((b) => (
                    <div key={b.employee_id + b.first_seen} className="rounded-md border p-2 text-sm">
                      <span className="font-mono text-xs">{b.employee_id}</span> · open {b.age_days} days (since {b.first_seen}) — {b.text}
                    </div>
                  ))}
                </div>
              </div>
              <div className="space-y-2">
                <h3 className="text-sm font-semibold">Milestones</h3>
                <Table>
                  <THead><TR><TH>Milestone</TH><TH>Due</TH><TH>Status</TH>{canEditMilestones && <TH />}</TR></THead>
                  <TBody>
                    {d.milestones.map((m) => (
                      <TR key={m.milestone_id}>
                        <TD>{m.name}</TD><TD className="whitespace-nowrap">{m.due_date}</TD>
                        <TD><Badge variant={m.status === "done" ? "success" : m.overdue ? "danger" : "secondary"}>{m.overdue ? "overdue" : m.status.replace("_", " ")}</Badge></TD>
                        {canEditMilestones && <TD>{m.status !== "done" && <Button size="sm" variant="outline" disabled={milestone.isPending} onClick={() => milestone.mutate({ id: m.milestone_id, status: "done" })}>Mark done</Button>}</TD>}
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </div>
              <div className="space-y-2">
                <h3 className="text-sm font-semibold">Members <span className="font-normal text-muted-foreground">(alphabetical)</span></h3>
                <Table>
                  <THead><TR><TH>Employee</TH><TH>Stand-ups</TH><TH>Last update</TH><TH>GitHub (commits · PRs · reviews)</TH><TH>Status</TH><TH /></TR></THead>
                  <TBody>
                    {d.members.map((m) => (
                      <TR key={m.employee_id}>
                        <TD className="font-mono text-xs">{m.employee_id}</TD>
                        <TD>{m.days_submitted}/{m.days_expected} <span className="text-xs text-muted-foreground">({pct(m.submission_rate)})</span></TD>
                        <TD className="whitespace-nowrap">{m.last_update ?? "—"}</TD>
                        <TD>{m.github.commits} · {m.github.prs_merged} · {m.github.reviews}</TD>
                        <TD className="space-x-1">{m.quiet && <Badge variant="warning">quiet</Badge>}{m.open_blocker && <Badge variant="warning">blocked</Badge>}{m.carryover_rate !== null && m.carryover_rate >= 0.5 && <Badge variant="outline">repeating plans</Badge>}</TD>
                        <TD><Button size="sm" variant="ghost" onClick={() => setPerson(m.employee_id)}>View record</Button></TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </div>
              {person && (rec.isLoading ? <Loader2 className="size-5 animate-spin" /> : rec.data && <PersonRecordView rec={rec.data} canReview />)}
            </>
          )}
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ people (HR) */
export function PeoplePage() {
  const { json } = useApi();
  const [input, setInput] = useState("");
  const [emp, setEmp] = useState<string | null>(null);
  const list = useQuery({ queryKey: ["employees"], queryFn: () => json<{ rows: { employee_id: string; department: string }[] }>("/api/employees") });
  const rec = useQuery({ queryKey: ["person", emp], enabled: !!emp, retry: false, queryFn: () => json<PersonRecord>(`/api/work/people/${emp}`) });
  return (
    <>
      <PageHeader title="Work records" description="Per-person evidence: stand-ups, blockers, GitHub activity and proof files. Every view is written to the audit log." />
      <form className="mb-6 flex max-w-md gap-2" onSubmit={(e) => { e.preventDefault(); setEmp(input.trim().toUpperCase()); }}>
        <Input list="emp-list" placeholder="EMP-1010" value={input} onChange={(e) => setInput(e.target.value)} />
        <datalist id="emp-list">{list.data?.rows.map((r) => <option key={r.employee_id} value={r.employee_id}>{r.department}</option>)}</datalist>
        <Button type="submit" disabled={!input.trim()}>Open</Button>
      </form>
      {rec.isLoading && <Loader2 className="size-5 animate-spin" />}
      {rec.isError && <p className="text-sm text-destructive">{(rec.error as Error).message}</p>}
      {rec.data && <PersonRecordView rec={rec.data} canReview />}
    </>
  );
}
