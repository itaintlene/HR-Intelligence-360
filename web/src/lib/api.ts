import { useAuth } from "@clerk/react";
import { useCallback } from "react";

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** Returns a fetch wrapper that attaches the Clerk session token to every request. */
export function useApi() {
  const { getToken } = useAuth();

  const raw = useCallback(
    async (path: string, init: RequestInit = {}) => {
      const token = await getToken();
      const headers = new Headers(init.headers);
      if (token) headers.set("Authorization", `Bearer ${token}`);
      const res = await fetch(`${BASE}${path}`, { ...init, headers });
      if (!res.ok) {
        let detail = res.statusText;
        try {
          detail = (await res.json()).detail ?? detail;
        } catch {
          /* non-JSON error body */
        }
        throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      return res;
    },
    [getToken],
  );

  const json = useCallback(async <T,>(path: string, init?: RequestInit): Promise<T> => (await raw(path, init)).json(), [raw]);

  const postJson = useCallback(
    <T,>(path: string, body: unknown) =>
      json<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
    [json],
  );

  const download = useCallback(
    async (path: string, filename: string) => {
      const blob = await (await raw(path)).blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    },
    [raw],
  );

  return { raw, json, postJson, download };
}
