import { UserButton, useAuth } from "@clerk/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate } from "@tanstack/react-router";
import { ArrowLeft, Loader2, Search } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/form";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { ApiError, useApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Me } from "@/lib/types";

interface AdminUser {
  id: string;
  email: string;
  name: string;
  role: string | null;
  hr_level: string | null;
  employee_id: string | null;
  last_sign_in_at: number | null;
  banned: boolean;
  bootstrap_admin: boolean;
  is_you: boolean;
}

interface Settings {
  email_mode: "env" | "off" | "redirect" | "live";
  email_redirect_to: string;
  resend_configured: boolean;
}

type SystemInfo = Record<string, string | number | boolean | null>;

const selectCls =
  "h-9 rounded-md border border-input bg-card px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";

/** /admin - users, roles, settings. Hidden from navigation; non-admins just see "not found". */
export function AdminPage() {
  const { isLoaded, isSignedIn } = useAuth();
  const { json } = useApi();
  const meQ = useQuery({ queryKey: ["me"], enabled: isLoaded && !!isSignedIn, retry: false, queryFn: () => json<Me>("/api/me") });
  const [tab, setTab] = useState<"users" | "settings" | "system">("users");

  if (!isLoaded || (isSignedIn && meQ.isLoading)) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (!isSignedIn) return <Navigate to="/sign-in/$" params={{ _splat: "" }} />;
  if (!meQ.data?.permissions.includes("manage_users")) {
    return (
      <div className="grid min-h-screen place-items-center p-6 text-center">
        <div>
          <h1 className="text-2xl font-semibold">Page not found</h1>
          <Link to="/app" className="mt-3 inline-block text-sm text-primary">
            Back to the app
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <header className="flex h-14 items-center justify-between border-b bg-card px-4 md:px-6">
        <div className="flex items-center gap-3">
          <Link to="/app" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
            <ArrowLeft className="size-4" /> App
          </Link>
          <span className="font-semibold">Admin console</span>
          <Badge variant="danger">restricted</Badge>
        </div>
        <UserButton />
      </header>
      <main className="mx-auto max-w-6xl space-y-6 p-4 md:p-8">
        <div className="flex gap-1 border-b">
          {(["users", "settings", "system"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn("-mb-px border-b-2 px-4 py-2 text-sm capitalize", tab === t ? "border-primary font-medium" : "border-transparent text-muted-foreground")}
            >
              {t}
            </button>
          ))}
        </div>
        {tab === "users" && <UsersTab />}
        {tab === "settings" && <SettingsTab />}
        {tab === "system" && <SystemTab />}
      </main>
    </div>
  );
}

function UsersTab() {
  const { json } = useApi();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const q = useQuery({
    queryKey: ["admin-users", query],
    queryFn: () => json<AdminUser[]>(`/api/admin/users${query ? `?query=${encodeURIComponent(query)}` : ""}`),
    retry: false,
  });
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Users &amp; roles</h1>
        <p className="text-sm text-muted-foreground">
          Everyone is an <b>employee</b> by default. Changes apply the next time the user signs in (or within about a minute).
        </p>
      </div>
      <form
        className="flex max-w-sm gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(search.trim());
        }}
      >
        <Input placeholder="Search by name or email" value={search} onChange={(e) => setSearch(e.target.value)} />
        <Button type="submit" variant="outline">
          <Search className="size-4" />
        </Button>
      </form>
      {q.isLoading && <Loader2 className="size-5 animate-spin" />}
      {q.isError && (
        <Card className="border-red-200">
          <CardContent className="pt-5 text-sm text-red-700">
            {(q.error as ApiError).message}
            {(q.error as ApiError).status === 503 && " — add CLERK_SECRET_KEY to the API's environment variables."}
          </CardContent>
        </Card>
      )}
      {q.data && (
        <Table>
          <THead>
            <TR>
              <TH>User</TH>
              <TH>Role</TH>
              <TH>HR level</TH>
              <TH>Employee ID</TH>
              <TH>Last sign-in</TH>
              <TH />
            </TR>
          </THead>
          <TBody>
            {q.data.map((u) => (
              <UserRow key={u.id} user={u} />
            ))}
          </TBody>
        </Table>
      )}
    </div>
  );
}

function UserRow({ user }: { user: AdminUser }) {
  const { sendJson } = useApi();
  const qc = useQueryClient();
  const [role, setRole] = useState(user.role ?? "employee");
  const [level, setLevel] = useState(user.hr_level ?? "staff");
  const [emp, setEmp] = useState(user.employee_id ?? "");
  const locked = user.is_you || user.bootstrap_admin;
  const dirty = role !== (user.role ?? "employee") || (role === "hr" && level !== (user.hr_level ?? "staff")) || emp !== (user.employee_id ?? "");
  const save = useMutation({
    mutationFn: () => sendJson("PUT", `/api/admin/users/${user.id}/role`, { role, hr_level: role === "hr" ? level : null, employee_id: emp.trim() || null }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });
  return (
    <TR>
      <TD>
        <div className="font-medium">
          {user.name || "—"} {user.is_you && <Badge variant="secondary">you</Badge>}{" "}
          {user.bootstrap_admin && <Badge variant="outline">bootstrap admin</Badge>}
        </div>
        <div className="text-xs text-muted-foreground">{user.email}</div>
        {save.isError && <div className="mt-1 max-w-xs text-xs text-destructive">{(save.error as Error).message}</div>}
      </TD>
      <TD>
        <select className={selectCls} value={role} disabled={locked} onChange={(e) => setRole(e.target.value)}>
          <option value="employee">Employee</option>
          <option value="pm">Project Manager</option>
          <option value="hr">HR</option>
        </select>
      </TD>
      <TD>
        {role === "hr" ? (
          <select className={selectCls} value={level} disabled={locked} onChange={(e) => setLevel(e.target.value)}>
            <option value="staff">Staff</option>
            <option value="manager">Manager (approves)</option>
            <option value="admin">Admin</option>
          </select>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </TD>
      <TD>
        <Input className="w-28" placeholder="EMP-1010" value={emp} disabled={locked} onChange={(e) => setEmp(e.target.value)} />
      </TD>
      <TD className="whitespace-nowrap text-xs text-muted-foreground">
        {user.last_sign_in_at ? new Date(user.last_sign_in_at).toLocaleString() : "never"}
      </TD>
      <TD>
        <Button size="sm" disabled={locked || !dirty || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? <Loader2 className="size-4 animate-spin" /> : "Save"}
        </Button>
      </TD>
    </TR>
  );
}

function SettingsTab() {
  const { json, sendJson } = useApi();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin-settings"], queryFn: () => json<Settings>("/api/admin/settings") });
  const [mode, setMode] = useState<Settings["email_mode"] | null>(null);
  const [redirect, setRedirect] = useState<string | null>(null);
  const cur = q.data;
  const m = mode ?? cur?.email_mode ?? "env";
  const r = redirect ?? cur?.email_redirect_to ?? "";
  const save = useMutation({
    mutationFn: () => sendJson("PUT", "/api/admin/settings", { email_mode: m, email_redirect_to: r }),
    onSuccess: () => {
      setMode(null);
      setRedirect(null);
      qc.invalidateQueries({ queryKey: ["admin-settings"] });
    },
  });
  if (!cur) return <Loader2 className="size-5 animate-spin" />;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Settings</h1>
      <Card>
        <CardHeader>
          <CardTitle>Email delivery</CardTitle>
          <CardDescription>
            Emails are only ever sent after an HR manager approves them.{" "}
            {cur.resend_configured ? "Resend is configured." : <b className="text-destructive">RESEND_API_KEY is not set on the server.</b>}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="mode">Mode</Label>
              <select id="mode" className={cn(selectCls, "w-full")} value={m} onChange={(e) => setMode(e.target.value as Settings["email_mode"])}>
                <option value="env">Follow server environment</option>
                <option value="off">Off — never send</option>
                <option value="redirect">Test — send everything to one address</option>
                <option value="live">Live — send to employees (needs a verified domain)</option>
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="redir">Test redirect address</Label>
              <Input id="redir" type="email" placeholder="you@example.com" value={r} onChange={(e) => setRedirect(e.target.value)} />
            </div>
          </div>
          {m === "live" && (
            <p className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm">
              Live mode emails real employee addresses. The demo data uses fake addresses — keep Test mode until you use real data and a verified sending domain.
            </p>
          )}
          {save.isError && <p className="text-sm text-destructive">{(save.error as Error).message}</p>}
          {save.isSuccess && <p className="text-sm text-emerald-700">Saved.</p>}
          <Button disabled={save.isPending || (mode === null && redirect === null)} onClick={() => save.mutate()}>
            Save settings
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

function SystemTab() {
  const { json } = useApi();
  const q = useQuery({ queryKey: ["admin-system"], queryFn: () => json<SystemInfo>("/api/admin/system") });
  if (!q.data) return <Loader2 className="size-5 animate-spin" />;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">System status</h1>
      <Table>
        <TBody>
          {Object.entries(q.data).map(([k, v]) => (
            <TR key={k}>
              <TD className="w-64 font-mono text-xs">{k}</TD>
              <TD>{typeof v === "boolean" ? <Badge variant={v ? "success" : "secondary"}>{v ? "yes" : "no"}</Badge> : String(v ?? "—")}</TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}
