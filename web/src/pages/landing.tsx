import { useAuth } from "@clerk/react";
import { Link, Navigate } from "@tanstack/react-router";
import { Briefcase, ShieldCheck, User } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PORTAL_KEY } from "@/lib/me";

const PORTALS = [
  { id: "employee", title: "Employee", icon: User, blurb: "Ask HR policy questions and get cited answers." },
  { id: "pm", title: "Project Manager", icon: Briefcase, blurb: "Policy answers plus pending leave requests from your team." },
  { id: "hr", title: "HR", icon: ShieldCheck, blurb: "Audits, onboarding automation, document processing and approvals." },
] as const;

export function Landing() {
  const { isLoaded, isSignedIn } = useAuth();
  if (isLoaded && isSignedIn) return <Navigate to="/app" />;
  return (
    <div className="mx-auto flex min-h-screen max-w-4xl flex-col justify-center px-6 py-12">
      <div className="mb-10 text-center">
        <div className="mx-auto mb-4 grid size-12 place-items-center rounded-xl bg-primary text-sm font-bold text-primary-foreground">360</div>
        <h1 className="text-3xl font-semibold tracking-tight">HR Intelligence 360</h1>
        <p className="mt-2 text-muted-foreground">Choose your portal to sign in.</p>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {PORTALS.map(({ id, title, icon: Icon, blurb }) => (
          <Link key={id} to="/sign-in/$" params={{ _splat: "" }} onClick={() => sessionStorage.setItem(PORTAL_KEY, id)}>
            <Card className="h-full transition hover:border-primary hover:shadow-md">
              <CardHeader>
                <Icon className="mb-2 size-6 text-primary" />
                <CardTitle>{title} login</CardTitle>
                <CardDescription>{blurb}</CardDescription>
              </CardHeader>
              <CardContent className="text-sm font-medium text-primary">Continue →</CardContent>
            </Card>
          </Link>
        ))}
      </div>
      <p className="mt-8 text-center text-xs text-muted-foreground">Access level is assigned by your administrator. Demo uses synthetic data.</p>
    </div>
  );
}
