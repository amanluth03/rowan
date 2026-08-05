import { redirect } from "next/navigation";

import { AppShell } from "@/components/layout/app-shell";
import { ApiError } from "@/lib/api/client";
import { getMe } from "@/lib/api/read-models";
import { requireSession } from "@/lib/auth/session";

/**
 * The render-path guard for every authenticated screen.
 *
 * `proxy.ts` already redirects requests with no Supabase session, but it is a
 * UX convenience, not the security boundary, and it cannot see one state that
 * matters: a user who is *legitimately signed in to Supabase* but has no
 * Rowan organization. `getUser()` succeeds for them, so the proxy waves them
 * through; the first `apiFetch` then gets a 401 from `resolve_principal` and
 * throws an unhandled `ApiError` into the RSC stream. The user sees a crash
 * screen on every page with no way out — signing up again reports "already
 * registered", and signing in returns them right here.
 *
 * That happens whenever signup half-completes: the Supabase account is
 * created, then org bootstrap fails (backend down, network blip, a
 * misconfigured server). Rather than leaving the account bricked, send them
 * to /finish-setup, which creates the missing organization.
 */
export default async function AppGroupLayout({ children }: { children: React.ReactNode }) {
  await requireSession(); // no Supabase session at all -> /login

  try {
    await getMe();
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      // Signed in to Supabase, but no Rowan organization yet.
      redirect("/finish-setup");
    }
    throw e;
  }

  return <AppShell>{children}</AppShell>;
}
