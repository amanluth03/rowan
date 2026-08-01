/**
 * Refreshes the Supabase session cookie on every request and guards the
 * app routes.
 *
 * # ASSUMPTION: named `proxy.ts` (function `proxy`), not `middleware.ts`.
 * Next.js 16 deprecated the `middleware` file convention in favor of
 * `proxy` -- same mechanism, renamed to avoid confusion with Express-style
 * middleware (see node_modules/next/dist/docs/.../proxy.md's "Migration to
 * Proxy"). `middleware.ts` still works in 16.2.10 but is deprecated with no
 * reason here to keep the legacy name -- this is a from-scratch build, not
 * a migration. Task 13's brief predates this rename; later tasks import
 * from `lib/supabase/*` and `lib/auth/session.ts`, not from this file
 * directly, so the filename has no cross-task dependency.
 *
 * This is a convenience and a UX guard, NOT the security boundary. The
 * security boundary is the backend: every /api/v1 route verifies the JWT
 * itself (tests/test_route_auth_coverage.py enforces that structurally).
 * Proxy only decides which page a browser gets shown.
 */

import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login", "/signup", "/accept-invite"];

export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options),
          );
        },
      },
    },
  );

  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { pathname } = request.nextUrl;
  const isPublic = PUBLIC_PATHS.some((p) => pathname.startsWith(p));

  if (!user && !isPublic) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    // Preserve where they were heading so login can return them there.
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  if (user && (pathname === "/login" || pathname === "/signup")) {
    const url = request.nextUrl.clone();
    url.pathname = "/";
    url.search = "";
    return NextResponse.redirect(url);
  }

  return response;
}

export const config = {
  matcher: [
    // Everything except Next internals and static assets.
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
