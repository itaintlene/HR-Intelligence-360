import { createContext, useContext } from "react";
import type { Me } from "@/lib/types";

const MeContext = createContext<Me | null>(null);
export const MeProvider = MeContext.Provider;

export function useMe(): Me {
  const me = useContext(MeContext);
  if (!me) throw new Error("useMe must be used inside the authenticated area");
  return me;
}

export const PORTAL_KEY = "hr360.portal";
export const HOME: Record<string, string> = { employee: "/app/ask", pm: "/app/ask", hr: "/app/dashboard" };
