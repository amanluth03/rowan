# Rowan frontend

Next.js (App Router) UI for the Vendor COI Renewal Agent — the five key screens (activity feed, vendor list/detail, run trace timeline, human-review queue, onboarding), per the Key Screens list in the repo root `CLAUDE.md`.

## Getting started

```bash
npm install
cp .env.example .env.local   # see "Auth stub" below before running against a real backend
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Requires the backend running (`backend/README.md`'s quickstart) for anything beyond static rendering — this app has no mock-data fallback anymore; all reads/writes go through the real API.

## Auth stub — READ THIS BEFORE deploying or extending this app

This app is wired to the backend via a **development-only auth stub**, not real authentication. `src/lib/api/config.ts::getOrgId()` resolves the organization for every request from a single env var (`ROWAN_ORG_ID`), sent server-side as an `X-Rowan-Org-Id` header (`src/lib/api/client.ts`). There is no per-user login, no session, and no verification of who is making a request — only *which org* they act as, matching the identical stub on the backend side (`backend/README.md`'s "Org-scoping auth stub" section, `backend/app/api/deps.py::get_organization_id`).

This is deliberately centralized to one function so that wiring real auth (Supabase session → verified org) later is a one-function swap, not a search-and-replace across every Server Action. **Do not deploy this app publicly without replacing `getOrgId()` with real session-derived auth first** — anyone who can reach a public deployment can act as the configured org.

## Architecture notes

- `src/app/actions.ts` — Server Actions, the Interface→Orchestration command transport (ADR 0003). Calls the real backend via `src/lib/api/client.ts`.
- `src/lib/api/read-models.ts` — assembles the four read-model DTOs (`RunTraceDTO`, `ActivityFeedItemDTO`, `VendorStatusDTO`, `ReviewQueueItemDTO`) from backend responses.
- `src/app/api/documents/[documentId]/route.ts` — proxies the backend's hardened document-download route, attaching the server-side org header the browser can't be trusted to send. Validates `documentId` against the UUID shape before forwarding (closes a path-traversal/confused-deputy risk found at security review).
- `src/lib/mock/` — retained for local component development/tests; no longer in the live request path.

See the repo root `CLAUDE.md` and `docs/adr/` for the full system design.
