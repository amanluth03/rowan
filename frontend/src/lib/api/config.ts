/**
 * Server-only backend config -- the single seam for org resolution + API
 * base URL, mirroring the backend's own dev-auth stub
 * (`backend/app/api/deps.py::get_organization_id`, documented in
 * backend/README.md's "Org-scoping auth stub").
 *
 * # ASSUMPTION: no real auth exists yet (backend-engineer's own stub;
 * security-reviewer flagged it as fail-closed-but-a-stub, not blocking).
 * `ROWAN_ORG_ID` is read from a server-side env var, resolved in exactly one
 * function (`getOrgId`) -- when real Supabase auth lands, this is the one
 * place that changes (env lookup -> verified-session claim), matching
 * backend's one-seam design. Every Server Action / Server Component /
 * Route Handler in this app must go through this function; never accept
 * `organizationId` from client input (a form field, a query param, a cookie
 * a user can edit) -- see this file's sibling `actions.ts`'s original
 * docstring on exactly this trap, which the backend's own README calls out
 * as "the same shape of trap flagged in the frontend's actions.ts docstring."
 *
 * This module is imported only by files that never run in the browser
 * (Server Actions marked "use server", Server Components, Route Handlers)
 * -- there is no client bundle boundary to enforce here beyond that
 * discipline (the `server-only` package would add a build-time guard but
 * isn't in this project's dependencies; noted as a low-cost follow-up).
 */

export const API_BASE = (process.env.ROWAN_API_BASE ?? "http://localhost:8000").replace(/\/$/, "");

export function getOrgId(): string {
  const orgId = process.env.ROWAN_ORG_ID;
  if (!orgId) {
    throw new Error(
      "ROWAN_ORG_ID is not set. Set it to a real organization UUID in frontend/.env.local -- " +
        "see backend/migrations/0009_seed.sql for the seeded demo org " +
        "(00000000-0000-7000-8000-000000000001), or POST /api/v1/vendors against a fresh " +
        "database to create your own. This is the dev-mode auth stub's single seam -- see " +
        "backend/README.md's 'Org-scoping auth stub' note.",
    );
  }
  return orgId;
}
