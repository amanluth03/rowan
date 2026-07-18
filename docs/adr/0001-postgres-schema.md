# ADR 0001 — Postgres schema, RLS, indexes, migration plan

**Status:** Proposed
**Layer:** Retrieval/memory (tier a run-state, tier b entity, tier c requirements) + Observability
**Depends on:** none. Depended on by: 0002, 0004, 0005.

## Decision

A single Supabase Postgres database, one schema (`public`), multi-tenant by
`organization_id` with Row-Level Security forced on every tenant table. No
vector column, no separate analytics store (both are non-goals in v1).

### Conventions (see 0000)

UUID v7 `id` PKs generated app-side; `timestamptz` UTC everywhere; integer
whole-dollars for coverage limits; integer cents for spend; native Postgres
enums for closed sets. All tenant tables carry `organization_id uuid not null`.

### Enum types

```
coverage_type      : general_liability | auto_liability | workers_comp |
                     umbrella_excess | professional_liability | pollution |
                     employers_liability
vendor_role        : plumber | electrician | hvac | general_contractor |
                     landscaper | roofer | cleaner | pest_control | other
property_type      : single_family | multi_family | condo | commercial | mixed_use
run_state          : monitoring | renewal_due_soon | first_outreach_sent |
                     awaiting_vendor_response | document_received | parsing |
                     validating | filed | needs_human_review | escalated_to_pm |
                     errored
run_status         : active | paused | completed | errored
event_type         : state_transition | tool_call | llm_call | guardrail_trip |
                     human_intervention | error | note
event_severity     : info | warn | error
doc_status         : received | parsing | parsed | filed | rejected | superseded
doc_source         : email_inbound | manual_upload | onboarding_import
email_direction    : outbound | inbound
escalation_kind    : needs_human_review | escalated_to_pm
escalation_status  : open | acknowledged | resolved
validation_result  : pass | fail
```

### Tables

**organizations** — tenant root.
`id · name · agent_enabled bool default true (per-org kill switch) · settings jsonb · created_at`

**users** — PM/owner accounts. `id · organization_id · auth_user_id (Supabase auth uid, unique) · email · full_name · role (owner|pm) · created_at`.
`# ASSUMPTION: single user per org in v1 (multi-user orgs are a non-goal). users still exists so escalations have a target and RLS can key on auth.uid().`

**properties** — servicing context + jurisdiction for tier-c predicate.
`id · organization_id · name · line1 · city · state · county · postal_code · country default 'US' · hoa_name (nullable) · property_type · attributes jsonb · created_at`

**vendors** — `id · organization_id · name · primary_email · vendor_role · status (active|inactive) · primary_property_id (nullable → properties; resolves the requirements context, see below) · notes · created_at`

**vendor_properties** — which properties a vendor services (many-to-many).
`id · organization_id · vendor_id · property_id · created_at`, `unique(vendor_id, property_id)`.

**compliance_requirements** — tier-c curated knowledge base (0005). Retrieved by predicate; NOT edited by the agent.
`id · organization_id · jurisdiction_state · jurisdiction_city (nullable = any) · jurisdiction_hoa (nullable) · property_type (nullable = any) · vendor_role (nullable = any) · coverage_type · min_each_occurrence (int dollars, nullable) · min_aggregate (int dollars, nullable) · requires_additional_insured bool · requires_waiver_of_subrogation bool · requires_primary_noncontributory bool · min_policy_notes text · source_citation text NOT NULL · source_url text · last_verified_at timestamptz NOT NULL · verified_by · active bool default true · created_at · updated_at`

**vendor_coverage_requirements** — the vendor's ONE effective required set (locked decision: one set per vendor, org-wide). Materialized from the retriever at onboarding, PM-confirmable. Each line traces to the KB row that justifies it (faithfulness + citation).
`id · organization_id · vendor_id · coverage_type · min_each_occurrence · min_aggregate · requires_additional_insured bool · requires_waiver_of_subrogation bool · requires_primary_noncontributory bool · source_compliance_requirement_id (nullable → compliance_requirements) · confirmed_by_pm bool default false · created_at · updated_at`, `unique(vendor_id, coverage_type)`.
`# ASSUMPTION: a null source_compliance_requirement_id means a PM-entered override with no KB backing; validation flags any such line as "unverified requirement" so faithfulness isn't silently bypassed.`

**coi_documents** — the raw certificate blob + renewal-history lifecycle. "COI document versions" = the ordered sequence of certificates for a vendor.
`id · organization_id · vendor_id · run_id (nullable) · storage_path (Supabase Storage) · original_filename · content_type · byte_size · sha256 (dedupe) · source · version_number int (per vendor) · supersedes_document_id (nullable self-FK) · status doc_status · valid_from date (nullable until parsed) · valid_to date (nullable) · is_current bool default false · received_at · uploaded_by (nullable) · created_at`, `unique(vendor_id, version_number)`, partial `unique(vendor_id) where is_current`.

**coi_extractions** — a parse result for a document (LLM extraction pass output). Multiple allowed (re-parse); one `is_current`.
`id · organization_id · run_id · coi_document_id · extracted jsonb (structured fields) · field_confidence jsonb · overall_confidence numeric · model · prompt_hash · input_tokens · output_tokens · cost_cents · is_current bool · created_at`

**coi_validations** — result of validating a current extraction against `vendor_coverage_requirements` (all-or-nothing, locked decision).
`id · organization_id · run_id · coi_extraction_id · result validation_result · line_results jsonb (array; each entry references vendor_coverage_requirement_id + source_compliance_requirement_id + parsed_value + required_value + pass bool + severity) · flags jsonb · faithfulness_ok bool · created_at`

**runs** — state-machine instance (tier-a). One active run per vendor renewal cycle.
`id · organization_id · vendor_id · coi_document_id (nullable) · state run_state default 'monitoring' · status run_status default 'active' · trigger (renewal_due|manual) · due_date date (expiry that triggered) · next_action_at timestamptz (scheduler wakeup) · outreach_email_count int default 0 · llm_call_count int default 0 · cost_cents_spent int default 0 · budget_cost_cap_cents int (from org settings) · reply_token text unique · reply_token_expires_at timestamptz · paused_by (nullable) · started_at · updated_at · completed_at (nullable)`.
Partial `unique(vendor_id) where status = 'active'` — at most one live run per vendor.

**tool_invocations** — idempotency ledger backing all side-effecting tools (0004).
`id · organization_id · run_id · tool_name · idempotency_key · request_hash · status (pending|succeeded|failed) · response jsonb · error jsonb · created_at · completed_at`, `unique(tool_name, idempotency_key)`.

**email_messages** — outreach + inbound tracking (tool + interface).
`id · organization_id · run_id · vendor_id · direction · provider_message_id (Resend id, nullable) · reply_token · subject · body_snapshot · to_email · from_email · status (queued|sent|delivered|bounced|received) · attachments_count int · created_at`

**agent_events** — append-only observability trace (tier: observability). Canonical; state transitions live here (`event_type='state_transition'`), so no duplicate transitions table.
`id · organization_id · run_id (nullable) · vendor_id (nullable) · event_type · name text (OTel-compatible span name) · severity · from_state (nullable) · to_state (nullable) · tool_name (nullable) · idempotency_key (nullable) · llm_model (nullable) · prompt_hash (nullable) · input_tokens · output_tokens · cost_cents · latency_ms · payload jsonb · created_at`.
`# ASSUMPTION: agent_events is append-only and never UPDATEd; corrections are new rows. Keeps the trace immutable for audit/trust.`

**escalations** — human-review queue AND PM escalations (one table, `kind` discriminator).
`id · organization_id · run_id · vendor_id · kind escalation_kind · reason_code text · severity event_severity · summary text (human-readable) · details jsonb (validation flags) · status escalation_status default 'open' · assigned_user_id (nullable) · resolution text (nullable: approved|rejected|revision_requested|acknowledged) · resolved_by (nullable) · created_at · resolved_at (nullable)`.

**daily_rollups** — precomputed observability rollup (nightly job).
`id · organization_id · date · runs_started · runs_completed · runs_escalated · guardrail_trips · llm_cost_cents · created_at`, `unique(organization_id, date)`.
`# ASSUMPTION: rollup is a materialized nightly job, not live aggregation, to keep the daily digest cheap. Live counts come from agent_events when needed.`

## RLS shape

Every tenant table (all above except none — organizations included) gets:

```sql
alter table <t> enable row level security;
alter table <t> force row level security;
create policy tenant_isolation on <t>
  using      (organization_id = current_setting('app.current_org', true)::uuid)
  with check (organization_id = current_setting('app.current_org', true)::uuid);
```

- The FastAPI backend connects as role **`rowan_app`** (no `BYPASSRLS`) and issues
  `SET LOCAL app.current_org = '<uuid>'` at the start of every request
  transaction, deriving the org from the verified Supabase JWT (`users.auth_user_id`).
- Background paths (scheduler, Resend webhook) resolve org first — the scheduler
  iterates orgs and sets the GUC per org; the webhook maps `reply_token → run →
  organization_id` then sets the GUC — so RLS holds even on system paths. A
  narrow **`rowan_system`** role exists for the org-enumeration query only
  (reads `organizations.id` where `agent_enabled`), nothing tenant-scoped.
- `organizations` policy keys on the same GUC (its own `id`).
- `# ASSUMPTION: no cross-org queries exist in product code; any that appear are a design smell and must be justified in review. Supabase service_role key is never used from request-path code — only in migrations/seed.`

## Indexes

- FK columns: index every `*_id` FK (Postgres does not auto-index FKs).
- Tenant hot paths: `(organization_id, ...)` composite leading with org id.
- `runs (organization_id, state) where status='active'` — scheduler & feed.
- `runs (next_action_at) where status='active'` — scheduler wakeups.
- `runs (reply_token)` unique — webhook lookup.
- `agent_events (run_id, created_at)` — trace timeline render.
- `agent_events (organization_id, created_at desc)` — activity feed.
- `agent_events (event_type, created_at) where event_type='guardrail_trip'` — safety dashboards.
- `tool_invocations (tool_name, idempotency_key)` unique — dedupe.
- `compliance_requirements (organization_id, jurisdiction_state, vendor_role, coverage_type) where active` — tier-c predicate (0005).
- `coi_documents (vendor_id) where is_current` partial unique.
- `escalations (organization_id, status, kind)` — review queue.

## Migration plan

Supabase SQL migrations, forward-only in prod but each reversible in dev,
applied in dependency order:

1. `0001_extensions` — `pgcrypto` (gen_random_uuid fallback), UUID v7 helper.
2. `0002_enums` — all enum types above.
3. `0003_core` — organizations, users, properties, vendors, vendor_properties.
4. `0004_requirements` — compliance_requirements, vendor_coverage_requirements.
5. `0005_documents` — coi_documents, coi_extractions, coi_validations.
6. `0006_runs` — runs, tool_invocations, email_messages.
7. `0007_observability` — agent_events, escalations, daily_rollups.
8. `0008_rls` — enable/force RLS + tenant_isolation policies + roles
   (`rowan_app`, `rowan_system`) and grants.
9. `0009_seed` — one demo org, demo properties/vendors, and a starter
   `compliance_requirements` set for the demo jurisdiction (feeds evals/demo).

## Consequences

- Strong tenant isolation via forced RLS + GUC; no app-code query can leak
  across orgs even on a bug, as long as the GUC contract holds.
- "One requirement set per vendor" is enforced by the `unique(vendor_id,
  coverage_type)` constraint on `vendor_coverage_requirements`.
- All-or-nothing validation is a single `coi_validations` row with `result`.
- Idempotency is a first-class table, not an ad-hoc key — 0004 builds on it.
- Renewal history is queryable via `coi_documents.version_number` chain.

## Amendment (2026-07-18): four gaps resolved after backend build

Companion to ADR 0002's amendment (state-machine side) and ADR 0004's
amendment (tool-contract side) — same four items from `backend/README.md`'s
"Known gaps," resolved together.

**4. `rowan_system` grant, corrected and ratified.** The original text above
("the org-enumeration query only... nothing tenant-scoped") was incomplete:
it named the scheduler's read path but not the inbound-webhook's, which
also has to run before any org context exists (the webhook has no JWT to
derive `app.current_org` from — it has only a `reply_token` from the email
body). backend-engineer's extension is the correct minimal grant and is
ratified as the design:

```sql
grant select on organizations to rowan_system;
grant select (id, organization_id, reply_token, reply_token_expires_at, status)
  on runs to rowan_system;
```

plus a permissive RLS policy scoped to the `rowan_system` role only, on each
of those two tables, allowing an unfiltered `SELECT` (`organizations` for
org-enumeration; `runs` for reply-token resolution). This is safe because:
(a) it is **column-restricted** on `runs` — `rowan_system` cannot read
`coi_document_id`, `outreach_email_count`, or any other tenant business
data through this grant, only the five columns needed to resolve
`reply_token → run_id → organization_id` and check token expiry/run status;
(b) it is **row-unfiltered but not table-unfiltered** — the role has no
grant at all on any other tenant table, so there is no general bypass, only
these two narrow reads; (c) `rowan_app` (the request-path role) is
untouched — this grant adds no visibility to normal request handling, only
to the two system paths (scheduler tick, webhook) that must run before a
tenant context exists. The `runs(reply_token)` unique index (already listed
above) backs this lookup. Both grant and policy live in
`migrations/0008_rls.sql`, already implemented as described.

**3. `runs.llm_call_count` reset semantics, specified.** The schema above
lists `llm_call_count int default 0` on `runs` without saying when it
resets — ADR 0002's `MAX_LLM_PER_DOC` cap is per-document, but this is a
single run-level counter, not a per-document table. Resolved: it resets to
`0` whenever a new `coi_document_id` transitions `document_received →
parsing` (i.e. a fresh document — including a re-submitted one after a
PM-requested revision — gets a fresh per-document LLM budget). It is NOT
reset at any other transition. `cost_cents_spent` (also on `runs`) is a
**separate, run-cycle-scoped** counter and must NOT be reset alongside it —
see ADR 0002's and ADR 0004's amendments for the bug this conflation caused
in the initial build and the one-line fix. `# ASSUMPTION: a per-document
counter stays a reset-on-transition run-level column rather than a separate
`coi_document_id`-keyed table, to avoid adding a table for a value that only
ever needs "current document's count" — acceptable because there is at most
one document actively in `parsing` per run at a time (locked all-or-nothing
scoping). Revisit if v2 ever parses documents concurrently within one run.`

**1. `revision_request` budget scoping** and **2. no new `classify_document`
tool** — no schema change; see ADR 0002's and ADR 0004's amendments.
