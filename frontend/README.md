# Rowan frontend

Next.js (App Router) UI for the Vendor COI Renewal Agent — the five key screens (activity feed, vendor list/detail, run trace timeline, human-review queue, onboarding), per the Key Screens list in the repo root `CLAUDE.md`.

## Getting started

```bash
npm install
cp .env.example .env.local   # see "Auth stub" below before running against a real backend
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Requires the backend running (`backend/README.md`'s quickstart) for anything beyond static rendering — this app has no mock-data fallback anymore; all reads/writes go through the real API.

## Authentication

Real Supabase Auth. The dev-only `getOrgId()` / `X-Rowan-Org-Id` stub that used to live here is **deleted, with no fallback** — a fallback would be a bypass.

**This app never names an organization.** It forwards the user's Supabase access token as `Authorization: Bearer`, and the backend derives the org from the verified JWT (`backend/app/api/deps.py::get_principal`). That is the point: a client-supplied tenant id is now structurally impossible rather than merely discouraged.

| File | Role |
|---|---|
| `src/lib/supabase/server.ts` | Cookie-backed server client. Server Components / Actions / Route Handlers only. |
| `src/lib/supabase/browser.ts` | Browser client — used only by the login, signup, and accept-invite forms, which must call `signUp` / `signInWithPassword` directly. |
| `src/lib/auth/session.ts` | `getSession()` / `requireSession()`. Calls `supabase.auth.getUser()` to re-validate against the auth server — trusting the cookie alone is forgeable. |
| `src/proxy.ts` | Route guard. Next 16 renamed the `middleware` file convention to `proxy`. |
| `src/lib/api/client.ts` | Attaches the bearer token; fails closed with `ApiError(401)` if there is no session. |

**The route guard is a UX convenience, not the security boundary.** The backend verifies every request independently and returns 403/404 regardless of what this app renders. The same applies to role-aware UI: hiding an owner-only button is cosmetic, never a permission.

### Environment

```bash
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
ROWAN_API_BASE=http://localhost:8000
```

Both `NEXT_PUBLIC_*` values are **public by design** — the anon key is a client-side identifier constrained by Supabase policy, not a secret. **Never put a service-role key in this app**, and never in a `NEXT_PUBLIC_` variable.

> **Not yet verified end to end.** No Supabase project has been provisioned, so signup, login, and invite acceptance have never actually run. This builds clean and is unit-tested against a mocked session — that is not the same as working. With the env vars empty, `proxy.ts` currently 500s on every route.

## Architecture notes

- `src/app/actions.ts` — Server Actions, the Interface→Orchestration command transport (ADR 0003). Calls the real backend via `src/lib/api/client.ts`.
- `src/lib/api/read-models.ts` — assembles the four read-model DTOs (`RunTraceDTO`, `ActivityFeedItemDTO`, `VendorStatusDTO`, `ReviewQueueItemDTO`) from backend responses.
- `src/app/api/documents/[documentId]/route.ts` — proxies the backend's hardened document-download route, attaching the session's bearer token server-side. Validates `documentId` against the UUID shape before forwarding (closes a path-traversal/confused-deputy risk found at security review).
- `src/app/(auth)/` — login, signup, and accept-invite screens. Outside the app shell: no nav, no sidebar.
- `src/app/(app)/settings/team/` — owner-only. Invite an assistant, list pending invitations, revoke.
- `src/lib/mock/` — retained for local component development/tests; no longer in the live request path.

See the repo root `CLAUDE.md` and `docs/adr/` for the full system design.
