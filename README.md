# Rowan

**The AI back office for residential property managers, starting with compliance.**

Rowan is an agent, not a tracker. The first shipped capability is the **Vendor COI Renewal Agent**: when a vendor's certificate of insurance approaches expiry, Rowan emails the vendor, receives the renewed certificate, reads it, validates the coverage against the property manager's requirements, files it as evidence, and reports that it's handled — or escalates with specifics when something's wrong.

The target user is an independent residential property manager running 10–100 units across two or more jurisdictions in a high-regulation state. She is deeply liability-aware: her licence and her owners' trust are on the line. She doesn't want another dashboard to check. She wants work taken off her plate, and proof it was done right.

That last part is why this codebase looks the way it does. **Trust is the product**, so every claim in the UI carries evidence, every state transition is recorded, and the guardrails are enforced structurally rather than by convention.

---

## Table of contents

- [Repository layout](#repository-layout)
- [Architecture: the six-layer model](#architecture-the-six-layer-model)
- [The state machine](#the-state-machine)
- [Data model and tenant isolation](#data-model-and-tenant-isolation)
- [Authentication and roles](#authentication-and-roles)
- [Running locally](#running-locally)
- [Testing](#testing)
- [Evals and CI](#evals-and-ci)
- [Documentation map](#documentation-map)
- [Known gaps](#known-gaps)

---

## Repository layout

```
rowan/
├── CLAUDE.md              Shared ground truth. Read this first — it is the
│                          contract every contributor and agent works against.
├── backend/               FastAPI service: orchestration, tools, migrations,
│                          webhooks, scheduler.
├── frontend/              Next.js App Router UI (activity feed, vendors,
│                          run traces, review queue, onboarding).
├── tests/evals/           Golden-document eval harness. Separate from
│                          backend/tests — see "Evals and CI" below.
├── docs/                  ADRs, product context, delivery notes.
└── .github/workflows/     CI (three-tier eval pipeline).
```

### `backend/`

```
backend/
├── app/
│   ├── api/               Layer 1. FastAPI routes, request/response schemas,
│   │                      auth dependencies. No business rules live here.
│   ├── orchestration/      Layer 2. The deterministic, persisted state
│   │                      machine and its scheduler. This IS the planner —
│   │                      there is no free-roaming agent loop.
│   ├── tools/              Layer 3. Typed, contract-validated, side-effectful
│   │                      capabilities. The LLM never touches the database or
│   │                      the email provider directly, only these.
│   ├── retrieval/          Layer 4. Run state, entity lookup, requirements
│   │                      retrieval, principal/invitation resolution.
│   ├── policy/             Layer 5. Guardrails, action allowlists, role
│   │                      permissions, JWT verification, rate limiting.
│   ├── observability/      Layer 6. `agent_events` — the trace that the run
│   │                      detail view renders.
│   ├── notifications/      Account-lifecycle email (invitations). Deliberately
│   │                      separate from the run-scoped `send_email` tool.
│   ├── models/             Enums and tool contracts shared across layers.
│   ├── webhooks/           Inbound email (Resend) with signature verification.
│   ├── db.py               The two connection pools and `org_scoped_tx` — the
│   │                      single place an RLS-scoped transaction is opened.
│   └── config.py           Env-driven settings, all overridable.
├── migrations/            Numbered SQL, applied in filename order.
├── scripts/migrate.py     Migration runner (admin DSN, transaction per file).
└── tests/                 Unit and integration tests (310 at time of writing).
```

### `frontend/`

```
frontend/src/
├── app/
│   ├── (app)/             Authenticated application shell.
│   │   ├── page.tsx           Activity feed — the hero surface.
│   │   ├── vendors/           Vendor list and detail (COI status, history).
│   │   ├── runs/[runId]/      Run trace timeline — every step, and why.
│   │   ├── review/            Human-review queue, parsed-vs-required.
│   │   └── onboarding/        Add vendors, set coverage requirements.
│   └── api/               Route handlers that proxy to the backend.
├── components/            UI components (shadcn/Tailwind).
└── lib/api/               The single seam for all backend calls.
```

---

## Architecture: the six-layer model

Every change must map cleanly onto these layers, and **no function may reach across them**. This is enforced in review, and partly in tests.

| Layer | What it is |
|---|---|
| 1. Interface | Next.js UI and the API routes it calls |
| 2. Orchestration | The deterministic, persisted state machine |
| 3. Tools | Typed, contract-validated, side-effectful capabilities |
| 4. Retrieval | Run state, entity retrieval, requirements retrieval |
| 5. Policy | Guardrails, allowlists, kill switches, authz |
| 6. Observability | `agent_events`, the trace timeline, evals |

The practical consequence: **Orchestration, Tools, and Retrieval do not know that users exist.** They take an `organization_id`. Authentication and roles live only in Layers 1 and 5. This matters because the state machine also runs from the scheduler and the inbound-email webhook, where there is no user at all.

LLM calls happen only at bounded decision points — document extraction and coverage-gap explanation drafting. There is no free-roaming planning loop.

---

## The state machine

```
monitoring → renewal_due_soon → first_outreach_sent → awaiting_vendor_response →
document_received → parsing → validating → filed
                                        ↘ needs_human_review
                                        ↘ escalated_to_pm      → monitoring
```

Each state has an **explicit action allowlist** (`app/policy/actions.py`) — data, not scattered conditionals. An action outside the allowlist raises and transitions to `errored`.

The document pipeline is deliberately staged: classify → retrieve applicable requirements → extract → verify against requirements → structured flags → human-readable summary → route to human review on any high-severity flag. Each step gets its own prompt, its own eval, its own guardrails.

**Guardrails that are non-negotiable:**

- Inbound email content and attachments are **untrusted**. They are neutralised before reaching any LLM prompt, wrapped in delimiters and treated strictly as data.
- Every extraction output is schema-validated. Any failing field or sub-threshold confidence routes to `needs_human_review` — never guessed.
- The agent **never** auto-approves a COI that fails validation. Human review is mandatory for all invalid and low-confidence outcomes.
- If requirements retrieval returns nothing for a jurisdiction, the agent never guesses or falls back to defaults. It surfaces "no verified requirements on file" and escalates.
- Kill switches at three levels: per-run pause, per-org disable, and a global env flag that halts all outbound actions while leaving reads intact.

---

## Data model and tenant isolation

Isolation is enforced in **Postgres**, not in application code.

- Row-level security is `ENABLE`d **and** `FORCE`d on all 17 tenant tables.
- Each carries a `tenant_isolation` policy keyed on the `app.current_org` session GUC.
- The request-path role `rowan_app` has **no** `BYPASSRLS`.
- A second, deliberately narrow role `rowan_system` holds only SELECT, column-restricted, for the three lookups that are inherently cross-org and happen *before* an org is known: scheduler org enumeration, webhook reply-token resolution, and JWT-subject/invite-token resolution.

`app/db.py::org_scoped_tx` is the only sanctioned way to open a scoped transaction. **No query in this codebase should need `WHERE organization_id = ...` for isolation itself** — correctness must not depend on someone remembering a clause.

> One subtlety worth knowing: Postgres reverts custom GUCs to `''` (not `NULL`) after `set_config(..., is_local=true)` on a pooled connection. The policies therefore use `nullif(current_setting('app.current_org', true), '')::uuid`. A catalog-derived test enforces this on every tenant table so a future migration cannot silently reintroduce the old form.

---

## Authentication and roles

Supabase Auth issues the JWT; Rowan verifies it against the project JWKS (explicit algorithm allowlist, `iss`/`aud`/`exp` checked) and resolves it to a `Principal(user_id, auth_user_id, organization_id, role, email)`.

**The frontend never names an organization.** It forwards an access token; the backend derives the org. That makes the classic "client-supplied tenant id" bug structurally impossible rather than merely discouraged.

Two roles:

| | owner | assistant |
|---|:---:|:---:|
| Read everything in the org | yes | yes |
| Start / pause / resume a run, request a revision | yes | yes |
| Add vendors, set coverage requirements | yes | — |
| Approve / reject a COI, resolve an escalation | yes | — |
| Invite and remove team members | yes | — |

Authorization is a **default-deny data table** (`app/policy/permissions.py`): a command with no entry raises rather than allows, so adding a route without a role decision fails loudly.

The split is deliberate. Approving a COI is the moment Rowan tells the PM "you're covered" — her licence is on the line, so that sign-off stays with her. The chasing does not.

Signup creates an organisation with you as owner. Assistants join by emailed invitation: single-use, expiring, email-bound, and stored only as a SHA-256 hash — the plaintext token exists exactly once, in the email.

---

## Running locally

### Prerequisites

- **Docker** (for Postgres)
- **[uv](https://docs.astral.sh/uv/)** and Python ≥ 3.12 — `uv python install 3.12` will fetch the interpreter for you
- **Node.js** ≥ 20 and npm

### 1. Database

```bash
docker compose -f backend/docker-compose.yml up -d
```

Postgres 16 on **port 55432** (not 5432, to avoid colliding with a local install). Wait for the healthcheck to pass.

### 2. Backend

```bash
cd backend
cp .env.example .env          # then fill in the values below
uv sync

set -a; source .env; set +a   # migrate.py does not auto-load .env
uv run python scripts/migrate.py

uv run uvicorn app.main:app --reload
```

The API comes up on `http://localhost:8000`; interactive docs at `/docs`.

Environment variables worth knowing:

| Variable | Purpose |
|---|---|
| `ADMIN_DATABASE_URL` | Elevated DSN. **Migrations and seed only** — never request-path code. |
| `DATABASE_URL` | Request-path DSN, connects as the least-privilege `rowan_app` role. |
| `SYSTEM_DATABASE_URL` | Narrow `rowan_system` role, for pre-GUC lookups only. |
| `SUPABASE_URL` | Supabase project base URL. Empty ⇒ auth fails closed. |
| `ANTHROPIC_API_KEY` | Claude API. Empty ⇒ the extraction engine refuses to construct. |
| `RESEND_API_KEY` | Send-only credential, scoped least-privilege. |
| `ROWAN_KILL_SWITCH` | Global halt on all outbound actions; reads still work. |

Secrets live in env only. Never commit a real value — `.env.example` ships empty.

### 3. Frontend

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Runs on `http://localhost:3000`.

### Demo path

Add a vendor → set coverage requirements → simulate expiry → outreach → inbound document → parse → validate → file or escalate.

---

## Testing

```bash
cd backend

uv run pytest                              # full suite (needs Postgres up + migrated)
uv run pytest tests/test_validation_logic.py -q   # pure-logic subset, no DB needed
uv run ruff check .
```

Tests run against the **same local Postgres as development**, not a separate test database. Each test creates its own `organization_id`, so tests don't collide — but rows accumulate across runs. To reset:

```bash
docker compose -f backend/docker-compose.yml down -v
docker compose -f backend/docker-compose.yml up -d
# wait for healthy, then re-run migrate.py
```

**Two gotchas that have bitten us:**

1. `tool_invocations.unique(tool_name, idempotency_key)` and `invitations.token_hash` are **globally** unique, not per-org. Never write a test that inserts a *literal* into one — it collides with itself on the second run. Derive from a fresh UUID.
2. `scripts/migrate.py` does not auto-load `.env`. Source it first.

### Frontend

```bash
cd frontend
npm run test        # vitest
npm run lint
npx tsc --noEmit
```

---

## Evals and CI

`tests/evals/` is a **separate harness** from `backend/tests/`, with its own `pytest.ini` and requirements file. It scores the agent's behaviour on a golden set of COI documents — clean renewals, low limits, missing additional insureds, wrong dates, unparseable scans, and adversarial documents containing prompt-injection attempts.

It asserts the **full expected trajectory** per document — state transitions, guardrail trips, escalations — not just extraction accuracy. Plus retrieval-specific checks: correct requirements retrieved for a given jurisdiction, fallback fires on empty retrieval, and faithfulness (no asserted rule without a retrieved requirement ID).

CI runs three deliberately separated tiers (`.github/workflows/evals.yml`):

| Tier | When | Cost |
|---|---|---|
| `fixture-integrity` | always | offline, free |
| `trajectory-mocked` | always | offline, free |
| `golden-evals-real` | manual dispatch | calls the real Claude API |

```bash
cd tests/evals
pip install -r requirements-eval.txt
pytest
```

---

## Documentation map

| Path | What it is |
|---|---|
| `CLAUDE.md` | **Read first.** Company context, locked product decisions, architecture rules, non-goals. |
| `docs/context/product-context.md` | Market-research-derived build-priority guidance. |
| `docs/adr/` | Architecture decision records. *Gitignored* — see below. |
| `docs/what-rowan-does.md` | Plain-language capabilities and limits. |
| `docs/eval-results.md` | Eval run summary. |
| `backend/README.md` | Backend specifics: API surface, RLS shape, known gaps. |
| `frontend/README.md` | Frontend specifics. |

> **Note:** `docs/adr/` and `docs/superpowers/` are in `.gitignore`. The ADRs exist on the maintainer's machine and describe the design this codebase implements, but they are **not** in version control — a fresh clone will not have them. Their content is summarised in `CLAUDE.md` and in each module's docstrings.

---

## Known gaps

Stated plainly, because a compliance product that overstates its own completeness is the wrong product.

- **No Supabase project is provisioned yet.** The backend verifies JWTs against a JWKS endpoint and every test runs against an in-process fake, but nothing has been exercised end to end against a real Supabase tenant. Confirm the project issues **asymmetric** (RS256/ES256) tokens — a shared HS256 secret in backend env would let a leak forge any identity.
- **The frontend has not been migrated to bearer-token auth.** It still sends the removed `X-Rowan-Org-Id` header and will 401 against the current backend.
- **Invitation lifecycle events are not written to `agent_events`.** Team-membership changes are the highest-consequence human interventions in the system and should be traced before this ships.
- **A mailer failure during invite creation leaves an orphaned row.** The invitation commits before the email sends, so a transient failure — or engaging the global kill switch — blocks retries for the invite's 7-day lifetime.
- **Supabase Storage is not wired.** `app/storage.py`'s Protocol is the seam; the local filesystem implementation is dev-only.
- **Rate limiting is in-process** and keyed on client host, so it is not shared across instances and collapses to a single bucket behind a proxy.
- **No ownership transfer.** An organisation whose sole owner loses access has no recovery path.

### Deliberately not built

Payments, city portal integration, SMS, vendor portal logins, bulk import, OCR fallback, vector search, third-party observability platforms.

---

## Conventions

- **Assumptions are flagged in code** with `# ASSUMPTION: ...` comments. This is required, not optional — it is how we track what needs real customer validation.
- **Commit messages are short one-liners.** No `feat:`/`fix:` prefixes.
- **Migrations are immutable** once applied. Never edit a numbered file; add the next one.
- **The product is Rowan.** All user-facing strings, email templates, and page titles say so.
