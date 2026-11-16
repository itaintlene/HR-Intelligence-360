import { SignOutButton, useAuth } from "@clerk/clerk-react";
import { useQuery } from "@tanstack/react-query";
import { Navigate, Outlet } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { AppShell } from "@/components/layout";
import { Button } from "@/components/ui/button";
import { ApiError, useApi } from "@/lib/api";
import { HOME, MeProvider, PORTAL_KEY, useMe } from "@/lib/me";
import type { Me } from "@/lib/types";

const Centered = ({ children }: { children: ReactNode }) => (
  <div className="grid min-h-screen place-items-center p-6">
    <div className="max-w-md space-y-4 text-center">{children}</div>
  </div>
);

/** Layout for everything under /app: requires sign-in, a provisioned role, and (if chosen) the matching portal. */
export function AuthGate() {
  const { isLoaded, isSignedIn } = useAuth();
  const { json } = useApi();
  const meQ = useQuery({
    queryKey: ["me"],
    enabled: isLoaded && !!isSignedIn,
    retry: false,
    queryFn: () => json<Me>("/api/me"),
  });

  if (!isLoaded) return <Spinner />;
  if (!isSignedIn) return <Navigate to="/sign-in/$" params={{ _splat: "" }} />;
  if (meQ.isLoading) return <Spinner />;

  if (meQ.isError) {
    const forbidden = meQ.error instanceof ApiError && meQ.error.status === 403;
    return (
      <Centered>
        <h1 className="text-xl font-semibold">{forbidden ? "No access assigned" : "Cannot reach the server"}</h1>
        <p className="text-sm text-muted-foreground">
          {forbidden
            ? "Your account has no HR360 role yet. Ask an administrator to assign Employee, HR or Project Manager access."
            : (meQ.error as Error).message}
        </p>
        <SignOutButton>
          <Button variant="outline">Sign out</Button>
        </SignOutButton>
      </Centered>
    );
  }

  const me = meQ.data!;
  const chosen = sessionStorage.getItem(PORTAL_KEY);
  if (chosen && chosen !== me.portal_role) {
    return (
      <Centered>
        <h1 className="text-xl font-semibold">Wrong portal</h1>
        <p className="text-sm text-muted-foreground">
          This account is a <b>{me.portal_role.toUpperCase()}</b> account, but you chose the <b>{chosen.toUpperCase()}</b> login.
        </p>
        <div className="flex justify-center gap-2">
          <Button onClick={() => { sessionStorage.setItem(PORTAL_KEY, me.portal_role); window.location.assign(HOME[me.portal_role]); }}>
            Continue as {me.portal_role.toUpperCase()}
          </Button>
          <SignOutButton>
            <Button variant="outline">Sign out</Button>
          </SignOutButton>
        </div>
      </Centered>
    );
  }
  return (
    <MeProvider value={me}>
      <AppShell me={me} />
    </MeProvider>
  );
}

export function Require({ perm, children }: { perm: string; children: ReactNode }) {
  const me = useMe();
  if (!me.permissions.includes(perm)) {
    return <p className="rounded-md border p-4 text-sm text-muted-foreground">Your role does not have access to this page.</p>;
  }
  return <>{children}</>;
}

export function HomeRedirect() {
  const me = useMe();
  return <Navigate to={HOME[me.portal_role]} />;
}

export const Spinner = () => (
  <div className="grid min-h-screen place-items-center">
    <Loader2 className="size-6 animate-spin text-muted-foreground" />
  </div>
);

export { Outlet };
