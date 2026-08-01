/**
 * Server-side Supabase client, backed by the Next.js cookie store.
 *
 * This is the replacement for `lib/api/config.ts`'s `getOrgId()` env-var
 * stub. Where that read a hardcoded org id from the environment, this reads
 * a real session the user authenticated for.
 *
 * Server-only: imported exclusively by Server Components, Server Actions,
 * Route Handlers, and proxy.ts. Never from a "use client" module.
 */

import { createServerClient as createSSRClient } from "@supabase/ssr";
import { cookies } from "next/headers";

export async function createServerClient() {
  const cookieStore = await cookies();

  return createSSRClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options),
            );
          } catch {
            // Called from a Server Component, where cookies are read-only.
            // Proxy (src/proxy.ts) refreshes the session cookie on every
            // request instead, so it's safe to swallow this here -- it is
            // the documented @supabase/ssr pattern.
          }
        },
      },
    },
  );
}
