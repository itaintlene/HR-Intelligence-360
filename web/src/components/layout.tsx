import { UserButton } from "@clerk/react";
import { Link, Outlet } from "@tanstack/react-router";
import { Bell, CalendarDays, ClipboardCheck, History, LayoutDashboard, MessageSquare, ScrollText, Users, Workflow } from "lucide-react";
import type { ComponentType } from "react";
import { Badge } from "@/components/ui/badge";
import type { Me } from "@/lib/types";

interface NavItem {
  to: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  perm?: string;
}

const NAV: Record<string, NavItem[]> = {
  employee: [
    { to: "/app/ask", label: "Ask HR", icon: MessageSquare },
    { to: "/app/requests", label: "My questions", icon: History },
  ],
  pm: [
    { to: "/app/ask", label: "Ask HR", icon: MessageSquare },
    { to: "/app/team-leave", label: "Team leave", icon: CalendarDays },
    { to: "/app/requests", label: "My requests", icon: History },
  ],
  hr: [
    { to: "/app/dashboard", label: "Audit dashboard", icon: LayoutDashboard },
    { to: "/app/assistant", label: "Workflows", icon: Workflow },
    { to: "/app/approvals", label: "Approvals", icon: ClipboardCheck },
    { to: "/app/employees", label: "Employees", icon: Users },
    { to: "/app/requests", label: "All requests", icon: History },
    { to: "/app/team-leave", label: "Leave requests", icon: CalendarDays },
    { to: "/app/ask", label: "Ask policy", icon: MessageSquare },
    { to: "/app/audit-log", label: "Audit log", icon: ScrollText, perm: "view_audit_log" },
  ],
};

const ROLE_LABEL: Record<string, string> = { employee: "Employee", hr: "HR", pm: "Project Manager" };

export function AppShell({ me }: { me: Me }) {
  const items = (NAV[me.portal_role] ?? []).filter((i) => !i.perm || me.permissions.includes(i.perm));
  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-60 shrink-0 flex-col border-r bg-card md:flex">
        <div className="flex h-14 items-center gap-2 border-b px-4 font-semibold">
          <span className="grid size-7 place-items-center rounded-md bg-primary text-xs text-primary-foreground">360</span>
          HR Intelligence
        </div>
        <nav className="flex flex-1 flex-col gap-1 p-3">
          {items.map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
              activeProps={{ className: "bg-accent text-foreground font-medium" }}
            >
              <Icon className="size-4" /> {label}
            </Link>
          ))}
        </nav>
        <p className="border-t p-3 text-[11px] text-muted-foreground">Synthetic data · prototype</p>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b bg-card px-4 md:px-6">
          <nav className="flex gap-3 md:hidden">
            {items.slice(0, 3).map(({ to, label }) => (
              <Link key={to} to={to} className="text-xs text-muted-foreground" activeProps={{ className: "font-semibold text-foreground" }}>
                {label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <Badge variant="secondary">{ROLE_LABEL[me.portal_role]}</Badge>
            {me.employee_id && <span className="font-mono text-xs text-muted-foreground">{me.employee_id}</span>}
            <Bell className="hidden size-4 text-muted-foreground" />
            <UserButton />
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 p-4 md:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export function PageHeader({ title, description }: { title: string; description?: string }) {
  return (
    <div className="mb-6">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
    </div>
  );
}
