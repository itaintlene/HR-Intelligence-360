import { SignIn } from "@clerk/react";
import { createRootRoute, createRoute, createRouter, Outlet } from "@tanstack/react-router";
import { AuthGate, HomeRedirect, Require } from "@/pages/gate";
import { Landing } from "@/pages/landing";
import {
  ApprovalsPage, AskPage, AuditLogPage, DashboardPage, EmployeesPage, RequestsPage, TeamLeavePage, WorkflowsPage,
} from "@/pages/pages";
import { useMe } from "@/lib/me";
import { AdminPage } from "@/pages/admin";
import { MyWorkPage, PeoplePage, ProjectsPage, StandupPage } from "@/pages/work";

const rootRoute = createRootRoute({ component: () => <Outlet /> });

const landing = createRoute({ getParentRoute: () => rootRoute, path: "/", component: Landing });

const SignInPage = () => (
  <div className="grid min-h-screen place-items-center p-6">
    <SignIn routing="path" path="/sign-in" fallbackRedirectUrl="/app" />
  </div>
);
const signIn = createRoute({ getParentRoute: () => rootRoute, path: "/sign-in/$", component: SignInPage });

const app = createRoute({ getParentRoute: () => rootRoute, path: "/app", component: AuthGate });
const appIndex = createRoute({ getParentRoute: () => app, path: "/", component: HomeRedirect });

const ask = createRoute({ getParentRoute: () => app, path: "/ask", component: () => <Require perm="policy_query"><AskPage /></Require> });
const requests = createRoute({ getParentRoute: () => app, path: "/requests", component: RequestsPage });
const teamLeave = createRoute({
  getParentRoute: () => app,
  path: "/team-leave",
  component: () => {
    const me = useMe();
    return <Require perm="view_team_leave"><TeamLeavePage me={me} /></Require>;
  },
});
const dashboard = createRoute({ getParentRoute: () => app, path: "/dashboard", component: () => <Require perm="run_audit"><DashboardPage /></Require> });
const assistant = createRoute({ getParentRoute: () => app, path: "/assistant", component: () => <Require perm="run_workflow"><WorkflowsPage /></Require> });
const approvals = createRoute({
  getParentRoute: () => app,
  path: "/approvals",
  component: () => {
    const me = useMe();
    return <Require perm="run_workflow"><ApprovalsPage me={me} /></Require>;
  },
});
const employees = createRoute({ getParentRoute: () => app, path: "/employees", component: () => <Require perm="view_employee_masked"><EmployeesPage /></Require> });
const auditLog = createRoute({ getParentRoute: () => app, path: "/audit-log", component: () => <Require perm="view_audit_log"><AuditLogPage /></Require> });

// Admin console: intentionally NOT linked from the sidebar - reached by URL only, admins only (enforced server-side too).
const admin = createRoute({ getParentRoute: () => rootRoute, path: "/admin", component: AdminPage });

const standup = createRoute({ getParentRoute: () => app, path: "/standup", component: () => <Require perm="submit_standup"><StandupPage /></Require> });
const myWork = createRoute({ getParentRoute: () => app, path: "/my-work", component: () => <Require perm="view_own_work"><MyWorkPage /></Require> });
const projects = createRoute({
  getParentRoute: () => app,
  path: "/projects",
  component: () => {
    const me = useMe();
    return <Require perm="view_project_status"><ProjectsPage me={me} /></Require>;
  },
});
const people = createRoute({ getParentRoute: () => app, path: "/people", component: () => <Require perm="view_person_record"><PeoplePage /></Require> });

const routeTree = rootRoute.addChildren([
  landing,
  signIn,
  admin,
  app.addChildren([appIndex, standup, myWork, projects, people, ask, requests, teamLeave, dashboard, assistant, approvals, employees, auditLog]),
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
