import { ClerkProvider } from "@clerk/clerk-react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { router } from "./router";

const key = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string | undefined;
const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, refetchOnWindowFocus: false } } });

function MissingKey() {
  return (
    <div className="mx-auto max-w-lg p-10 text-sm">
      <h1 className="mb-2 text-xl font-semibold">Clerk is not configured</h1>
      <p>
        Copy <code>web/.env.example</code> to <code>web/.env.local</code> and set <code>VITE_CLERK_PUBLISHABLE_KEY</code>. See{" "}
        <code>docs/CLERK_SETUP.md</code>.
      </p>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {key ? (
      <ClerkProvider
        publishableKey={key}
        afterSignOutUrl="/"
        routerPush={(to) => router.navigate({ to })}
        routerReplace={(to) => router.navigate({ to, replace: true })}
      >
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </ClerkProvider>
    ) : (
      <MissingKey />
    )}
  </StrictMode>,
);
