/**
 * Thin fetch wrapper for every Interface -> Orchestration call this app
 * makes against the real backend (ADR 0003's 9 commands + 4 read-model
 * DTOs, see backend/README.md's "REST API" section). Centralizes: the base
 * URL, the `Authorization: Bearer` header (the user's real Supabase access
 * token, from `lib/auth/session.ts::getSession()` -- the backend derives
 * the organization from this verified token; the client never names one),
 * JSON (de)serialization, and turning a non-2xx response into a typed
 * `ApiError` callers can branch on.
 *
 * Every Server Action (`app/actions.ts`) and server-side data-fetcher
 * (`lib/api/read-models.ts`) goes through this, not a raw `fetch()` -- one
 * seam to update for retries/timeouts later.
 */

import { getSession } from "@/lib/auth/session";

import { API_BASE } from "./config";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `Rowan API request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

interface ApiFetchInit {
  method?: "GET" | "POST";
  body?: unknown;
}

export async function apiFetch<T>(path: string, init: ApiFetchInit = {}): Promise<T> {
  const session = await getSession();
  if (!session) {
    // Fail closed. Sending the request without credentials would produce a
    // confusing 401 from the backend; surfacing it here lets callers
    // redirect to /login with intent.
    throw new ApiError(401, "Not authenticated");
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method: init.method ?? "GET",
    headers: {
      Authorization: `Bearer ${session.accessToken}`,
      ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    // Every read here reflects mutable state a command may have just
    // changed (an approval, a new vendor, a paused run) -- never let Next's
    // fetch cache serve a stale response. `revalidatePath` in actions.ts is
    // belt-and-suspenders on top of this for cross-request Router Cache
    // entries, not a substitute for it.
    cache: "no-store",
  });

  const text = await res.text();
  const data = text.length > 0 ? JSON.parse(text) : undefined;

  if (!res.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? (data as { detail: unknown }).detail : data;
    throw new ApiError(res.status, detail);
  }

  return data as T;
}

/** GET helper that maps a 404 to `null` instead of throwing -- matches the
 * `T | null` "not found" shape every read-model getter in this app uses. */
export async function apiFetchOrNull<T>(path: string): Promise<T | null> {
  try {
    return await apiFetch<T>(path);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}
