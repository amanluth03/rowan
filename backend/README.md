# Rowan backend

FastAPI backend for the Vendor COI Renewal Agent (v1): Postgres schema +
migrations, the state-machine orchestration runner, the non-LLM tools layer,
the inbound-email webhook, and the scheduler. Built against
`docs/adr/0001`–`0005` — see those for the design this implements.

## Stack / tooling

- Python 3.12, managed with [`uv`](https://docs.astral.sh/uv/) (no separate
  venv steps needed — `uv run` handles it).
- FastAPI + `asyncpg` (raw SQL, no ORM) for the app.
- Plain numbered `.sql` migrations (`backend/migrations/`), applied by a
  small custom runner (`scripts/migrate.py`) rather than Alembic — this
  matches ADR 0001's migration plan exactly (9 files, in dependency order)
  without an ORM model layer to keep in sync with hand-written SQL.
- Postgres 16 via `docker-compose.yml` for local dev/test.
- `pytest` + `pytest-asyncio`, run against a real local Postgres (not
  mocked) — RLS, idempotency, and crash-recovery behavior are exactly the
  things that don't show up in a mocked DB.

## First-time setup

```bash
cd backend
uv sync                       # installs deps into backend/.venv
cp .env.example .env          # local dev defaults (docker-compose creds)
docker compose up -d          # local Postgres 16 on localhost:55432
# wait for it to be healthy:
until docker compose exec -T postgres pg_isready -U postgres; do sleep 1; done

# Apply all 9 migrations (creates rowan_app / rowan_system roles, RLS
# policies, and seeds one demo org/vendor). Uses the admin/superuser DSN —
# never the request-path credential — per ADR 0001.
export ADMIN_DATABASE_URL="postgresql://postgres:postgres@localhost:55432/rowan"
export ROWAN_APP_DB_PASSWORD="rowan_app_dev_password"
export ROWAN_SYSTEM_DB_PASSWORD="rowan_system_dev_password"
uv run python scripts/migrate.py
```

These three env vars only matter for the migration step; day-to-day
running/testing reads `DATABASE_URL` / `SYSTEM_DATABASE_URL` from `.env`
(already pointed at the same local Postgres by `.env.example`).

## Running the app

```bash
uv run uvicorn app.main:app --reload --port 8000
```

- `GET /health` — liveness check.
- `POST /webhooks/resend/inbound` — inbound-email webhook (Svix-signed;
  verifies `svix-id` / `svix-timestamp` / `svix-signature` headers against
  `RESEND_WEBHOOK_SECRET`).
- `POST /internal/scheduler/tick` — triggers one scheduler sweep. Protected
  by a static bearer token (`INTERNAL_TOKEN` env var) as a placeholder until
  it's wired to a real cron caller (Vercel Cron, etc.) — returns 503 if
  unconfigured, never silently open.
- `/api/v1/*` — the REST API the frontend calls (ADR 0003's 9 commands + 4
  read-model DTOs). See the "REST API" section below.

## REST API (`app/api/`)

Every route requires an `Authorization: Bearer <supabase-jwt>` header — **read
the "Authentication" note immediately below for how `organization_id` is
resolved from it.** All routes are rate-limited (`app/api/deps.py`, 120
req/60s per client IP, same in-process mechanism as the webhook's limiter).

**Commands** (ADR 0003 "Interface -> Orchestration: typed commands only" —
each validates its body with Pydantic, calls exactly one
`app/orchestration/runner.py` function, and returns a typed response):

| Method & path | Command | Notes |
|---|---|---|
| `POST /api/v1/vendors` | `AddVendor` | Creates the vendor AND its initial `runs` row in one transaction. Generates `reply_token` via `secrets.token_urlsafe(32)` and a real `reply_token_expires_at` — see the note below. |
| `POST /api/v1/vendors/{vendor_id}/requirements` | `SetRequirements` | Body `{}`/omitted `lines` → auto-retrieves from `compliance_requirements` via the vendor's `primary_property_id` jurisdiction context (ADR 0005); 422 if nothing found (fallback — never guesses). Explicit `lines` → PM-entered/overridden set. |
| `POST /api/v1/runs/{run_id}/start` | `StartRun` | Manual "start renewal now" — bypasses the scheduler's date guard; a NEW human-trigger variant on the existing `monitoring -> renewal_due_soon` edge, not a new state (see `app/orchestration/runner.py::start_run_now`'s docstring — flagged for architect review). |
| `POST /api/v1/runs/{run_id}/pause` | `PauseRun` | "PM takes over" (CLAUDE.md) — freezes the run via `runs.status='paused'`. |
| `POST /api/v1/runs/{run_id}/resume` | `ResumeRun` | Un-freezes; no transition, the run resumes from wherever it was frozen. |
| `POST /api/v1/reviews/{escalation_id}/approve` | `ApproveReview` | → `resolve_needs_human_review(decision='approve')`. |
| `POST /api/v1/reviews/{escalation_id}/reject` | `RejectReview` | → `resolve_needs_human_review(decision='reject')`. |
| `POST /api/v1/reviews/{escalation_id}/request-revision` | `RequestRevision` | → `resolve_needs_human_review(decision='request_revision')`. |
| `POST /api/v1/escalations/{escalation_id}/resolve` | `ResolveEscalation` | → `resolve_escalated_to_pm(...)` — the `kind='escalated_to_pm'` queue, distinct from the three above (`kind='needs_human_review'`). |

All four review/escalation commands take only an `escalation_id` (no
`run_id` in the path) — dispatch resolves `run_id` from the escalation and
validates `kind` + `status='open'` before delegating
(`app/orchestration/runner.py::_load_open_escalation_for_command`). This is
deliberate: see "Review-queue lookup, fixed" below.

**Read models** (ADR 0003 DTOs, assembled by `app/api/read_models.py` —
the one legitimate place Interface-layer code queries Retrieval, per ADR
0003 boundary rule #3):

| Method & path | DTO |
|---|---|
| `GET /api/v1/activity-feed?limit=` | `ActivityFeedItemDTO[]` |
| `GET /api/v1/vendors` | `VendorStatusDTO[]` |
| `GET /api/v1/vendors/{vendor_id}` | `VendorStatusDTO` |
| `GET /api/v1/runs/{run_id}/trace` | `RunTraceDTO` |
| `GET /api/v1/reviews?kind=needs_human_review\|escalated_to_pm` | `ReviewQueueItemDTO[]` |
| `GET /api/v1/reviews/{escalation_id}` | `ReviewQueueItemDTO` |
| `GET /api/v1/documents/{document_id}/download` | raw file bytes (backs every `DocumentRef.url` in the DTOs above) |

Wire shapes are in `app/api/schemas.py`, camelCase over the wire
(`CamelModel`, matching `frontend/src/lib/types.ts`'s proposed shape — see
"DTO shape notes for frontend-engineer" below for the handful of places this
implementation's real data can't match that proposal exactly).

### Authentication — `app/api/deps.py::get_principal`

`app/api/deps.py::get_principal` derives `organization_id` **only** from a
required `Authorization: Bearer <jwt>` header: the token is verified against
Supabase's JWKS (signature, `iss`, `aud`, `exp` — `app/policy/auth.py`),
then its `sub` claim is resolved to a Rowan `Principal` (user, org, role) via
`app/retrieval/principal_repo.py::resolve_principal`. `get_organization_id`
is kept as a one-line derivative of `get_principal` so existing route
signatures didn't need to change. Any failure in that chain (missing header,
bad signature, unknown `sub`) is a generic 401 — deliberately
undifferentiated, so a forgery attempt can't learn which stage failed.

# ASSUMPTION: every route depends on `get_principal` (directly, via
`get_organization_id`, or via `require_role`'s closure) for org
resolution — never a client-supplied body/query field. This is enforced
structurally, not just by convention: `tests/test_route_auth_coverage.py`
walks the live FastAPI router and fails CI if any `/api/v1` route's
dependency tree omits `get_principal`.

### Review-queue lookup, fixed (security-reviewer's flagged gap)

Prior review flagged: `entity_repo.get_open_escalation` (used internally by
`escalate_to_pm`'s own re-entry dedupe) finds an escalation by matching
`escalations.details->>'run_state'` against the run's state **at escalation
creation time** — correct for that narrow purpose, but wrong if reused as
the general "does this run have an open escalation" lookup, since a run's
state can move on after the escalation was created. The new review-queue
read path (`entity_repo.list_open_escalations`) and command dispatch
(`runner._load_open_escalation_for_command`) both look up **only by
`kind` + `status='open'`** (plus RLS org-scoping) — never by matching the
run's current state. Regression test:
`tests/test_orchestration_commands.py::TestApproveRejectRequestRevision::
test_dispatch_finds_escalation_even_when_run_state_has_moved_on` and
`tests/test_api_reads.py::TestReviewQueue::
test_review_queue_finds_escalation_even_if_run_state_has_moved_on`.

### DTO shape notes for frontend-engineer

`frontend/src/lib/types.ts` was written before this schema existed and is
flagged there as a proposal, not a ratified contract. Places the real data
genuinely can't match it 1:1:

- **`CurrentCoiDTO.filedAt`** — `coi_documents` has no separate `filed_at`
  column (ADR 0001); approximated as `received_at`, the closest timestamp
  actually on the row. Not the moment `file_document` flipped `is_current`.
- **`LineComparisonDTO.severity` / `FlagDTO.severity`** — `types.ts` types
  these as the full `EventSeverity` (`info|warn|error`), but the underlying
  data (`app/tools/validation_logic.py`'s `line_results`/`flags`) uses a
  `high`/`info` vocabulary, not `EventSeverity`'s. Mapped `high -> error`,
  everything else `-> info` (see `app/api/read_models.py::_dto_severity`) —
  `warn` never appears on these two fields in practice.
- **`ActiveRunSummaryDTO.dueDate`** (nested in `VendorStatusDTO.activeRun`)
  and **`RunTraceDTO.dueDate`** — nullable in the real schema
  (`runs.due_date` has no NOT NULL constraint; a freshly onboarded vendor
  with no known current-COI expiry gets `due_date=NULL` until a document is
  filed or a PM sets one) — `types.ts` currently types these non-null.
- **`VendorStatusDTO.primaryPropertyName` / `primaryPropertyJurisdiction`**
  — nullable here (a vendor's `primary_property_id` is nullable in ADR
  0001's schema), not present as optional in `types.ts`.

### Known gaps in the API layer itself

- **`AddVendor`'s `reply_token_expires_at`** — ADR 0001/0004 don't specify a
  lifetime for this token, and a `runs` row is long-lived (cycles
  `monitoring -> ... -> filed -> monitoring` indefinitely on the SAME
  `reply_token`, not reissued per cycle). Picked 2 years
  (`app/orchestration/runner.py::REPLY_TOKEN_VALIDITY_DAYS`) as a
  placeholder pending real rotation-policy input — flagged to architect.
- **`StartRun`** adds a `human`-triggered variant of the
  `monitoring -> renewal_due_soon` edge that ADR 0002 only specified a
  `scheduler` trigger for (bypassing the date guard entirely on explicit PM
  request). Same edge, same guarded cascade into `send_first_outreach` —
  no new state, no new edge shape — but it's still new enough to flag for
  architect sign-off rather than silently ship as "obviously fine."
- **N+1 KB joins** in `read_models.py` (one `compliance_requirements` fetch
  per requirement line / comparison line) — fine at demo scale, would want
  batching before real multi-vendor-portfolio load.
- **In-process rate limiter** — same multi-instance caveat as the webhook's
  (`app/policy/rate_limit.py`'s docstring); not shared across instances.

## Running tests

```bash
uv run pytest                 # full suite, needs docker compose up + migrated
uv run pytest tests/test_validation_logic.py -q   # pure-logic subset, no DB needed
```

Tests run against the SAME local Postgres as dev (not a separate test DB in
this pass — every test creates its own fresh `organization_id`/`vendor_id`
via the `org_and_vendor` fixture, so tests don't collide with each other,
but they DO accumulate rows over repeated runs). To reset to a clean slate:

```bash
docker compose down -v && docker compose up -d
# wait for healthy, then re-run the migrate step above
```

**Test isolation gotcha (bit us twice while building this — worth knowing):**
`tool_invocations.unique(tool_name, idempotency_key)` is intentionally
GLOBAL, not per-org (ADR 0001) — in production, keys are always derived
from UUIDs so this never collides. If you write a NEW test with a literal
short string as an idempotency-adjacent key (an email `sequence`, a `svix_id`,
etc.), make it unique per test run (e.g. suffix with `run_id` or a fresh
`uuid4()`), or it will pass in isolation and then fail the second time you
run the suite against the same un-reset local Postgres.

## Layout

```
app/
  config.py            Settings (env-loaded), org-overridable state-machine constants live in orchestration/constants.py
  db.py                Connection pools + org_scoped_tx() — the ONLY place that sets app.current_org
  ids.py                App-side UUID v7 generation
  storage.py            DocumentStorage Protocol; LocalFilesystemStorage for dev/test; Supabase Storage TODO
  api/
    deps.py                Supabase-JWT auth (get_principal/get_organization_id/require_role — see "REST API" above) + rate-limit dependency
    schemas.py               the 9 command request/response models + the 4 read-model DTOs, camelCase wire shape (CamelModel)
    commands.py                the 9 ADR 0003 command routes -> exactly one app/orchestration/runner.py call each
    read_models.py              DTO assembly (the "read-model service" ADR 0003 boundary rule #3 requires) -> app/api/reads.py routes call only this, never app/retrieval directly
    reads.py                    the 4 DTO GET routes + the document-download route
  models/
    enums.py             Python mirrors of the Postgres enums
    tool_contracts.py     ToolContext / ToolOutput / BudgetSnapshot / PendingEvent — the common tool envelope (ADR 0004)
    coi_fields.py          ExtractedCoiFields — the extraction<->validation contract (see "Interface for agent-engineer" below)
  policy/
    actions.py            Action enum + per-state ACTION_ALLOWLIST (ADR 0002)
    guardrails.py          Kill-switch / allowlist / budget PolicyDecision checks
    file_guardrails.py      Pre-LLM attachment validation (type/size/magic-byte sniffing) + untrusted-doc-text wrapper
  retrieval/
    models.py              Typed rows returned by every repository function
    entity_repo.py          Vendor/property/document/extraction/validation/escalation/email reads+writes
    run_repo.py              runs table CRUD, incl. the crash-recoverable CAS transition (update_run_state)
    requirements_retriever.py  RequirementsRetriever Protocol + V1DeterministicRetriever (ADR 0005)
  tools/
    idempotency.py           Shared tool_invocations reserve/complete mechanism (ADR 0004)
    keys.py                   Per-tool deterministic idempotency-key builders
    base.py                    budget_snapshot() / policy_precheck() helpers shared by tools
    update_coi_record.py        Read path (current requirements/COI/history) + write path (deterministic validation persistence)
    validation_logic.py          The all-or-nothing pass/fail comparison itself (pure function, heavily unit-tested)
    file_document.py             Marks a document current, supersedes the prior one
    mark_task_complete.py         The most-gated tool — hard precondition on validation pass OR human approval
    send_email.py                 Resend transport + email_messages persistence (two-phase, see crash-safety docstring)
    escalate_to_pm.py              Escalation upsert + PM notice
    parse_document.py              Wrapper/persistence shell; ExtractionEngine Protocol is agent-engineer's interface (see below)
    resend_client.py                Minimal Resend HTTP client (send-only; simulates sends if no API key configured)
    email_templates.py               Placeholder copy for all 5 templates
  orchestration/
    constants.py            Org-overridable state-machine config constants
    runner.py                 Every guarded transition — the state machine itself
    scheduler.py                Org enumeration (rowan_system) + per-org sweep, calls into runner.py
  observability/
    events.py                  agent_events writer (append-only)
  webhooks/
    resend_inbound.py            Signature verification + reply_token resolution + idempotent dispatch to runner.handle_inbound_document
  main.py                    FastAPI app: /health, /webhooks/resend/inbound, /internal/scheduler/tick, + app/api/'s routers
migrations/                0001..0009, applied in order by scripts/migrate.py
scripts/migrate.py         Migration runner (admin DSN only, never request-path)
tests/                     pytest, against a live local Postgres
```

## Interface left for agent-engineer (LLM extraction)

**File:** `app/tools/parse_document.py`
**What to implement:** the `ExtractionEngine` Protocol's `extract()` method,
then wire a real implementation into `parse_document(..., engine=YourEngine())`
(dependency-injected — nothing in `parse_document.py` imports a concrete
engine by default; `StubExtractionEngine` raises `NotImplementedError` until
you replace it).

```python
class ExtractionEngine(Protocol):
    async def extract(
        self, *, document_bytes: bytes, content_type: str, prompt_id: str, attempt_no: int
    ) -> ExtractionEngineResult: ...
```

- `ExtractionEngineResult.extracted` MUST be a valid
  `app.models.coi_fields.ExtractedCoiFields` — this is the shared contract
  with `app/tools/validation_logic.py`'s deterministic pass/fail comparison
  (backend-engineer's code, already built and tested — see
  `tests/test_validation_logic.py` for the 14 fixture cases it needs to
  keep passing).
- Route any document-derived text through
  `app.policy.file_guardrails.wrap_untrusted_document_text()` before it
  touches a prompt (CLAUDE.md pre-LLM guardrail — inbound documents are
  UNTRUSTED input).
- Raise `ExtractionEngineError` on any provider failure — don't catch and
  fabricate a low-confidence result; the shell's retry/budget bookkeeping
  depends on this.
- Full contract and rationale are in the module docstring at the top of
  `app/tools/parse_document.py`.

Also relevant to agent-engineer: `app/orchestration/runner.py`'s
`run_validation()` has a spot marked for the "coverage-gap explanation
drafting" LLM call (ADR 0002's second bounded decision point) — not yet
wired; currently `coi_validations.flags` (deterministic, structured) is all
that reaches `needs_human_review`/`escalated_to_pm`. Wiring a human-readable
explanation on top of those flags is a clean, additive next step — see the
`draft_explanation` action already reserved in the `validating` state's
allowlist (`app/policy/actions.py`).

## Resolved by architect (2026-07-18 amendment to ADRs 0001/0002/0004)

Four items originally flagged below as gaps were reviewed and resolved —
see the amendment sections in `docs/adr/0001`, `0002`, `0004`:

1. **`revision_request` counts against `MAX_OUTREACH`.** ADR 0002's explicit
   guard was confirmed authoritative over ADR 0004's stale budget-exempt
   assumption; no code change needed (`app/tools/send_email.py` already
   matched). `handled_notice`/`escalation_notice` remain budget-exempt.
2. **No new `classify_document` tool; classification folds into `parsing`**
   as a first LLM sub-pass (agent-engineer's territory, sharing the
   per-document LLM budget with extraction). Backend-engineer's
   deterministic stopgap (any file passing type/size guardrails is treated
   as a COI candidate until that sub-pass exists) was ratified as an
   acceptable interim state, not a deviation — see
   `app/orchestration/runner.py`'s `advance_from_document_received()`.
3. **`llm_call_count` resets per-document; `cost_cents_spent` does NOT.**
   Architect caught a real bug here: `advance_from_document_received` was
   resetting both counters together. `cost_cents_spent` is a per-run-cycle
   cap (CLAUDE.md: "max configurable $ per run") and must accumulate across
   every document/re-parse in one run cycle — otherwise repeated
   PM-requested revisions could blow past the cap in unbounded per-document
   increments. Fixed; regression test:
   `tests/test_orchestration_document_pipeline.py::
   test_cost_cents_spent_accumulates_across_documents_in_same_run_cycle`.
4. **`rowan_system`'s extended grant** (column-restricted SELECT on `runs`
   for the webhook's `reply_token -> run -> organization_id` resolution) was
   confirmed as the correct, smallest mechanism — ADR 0001 now documents it
   explicitly. See `migrations/0008_rls.sql`.

## Fixed by qa-evals-engineer's real-pipeline integration pass (2026-07-18)

qa-evals-engineer wired their eval harness to drive real orchestration code
end-to-end (18/18 golden fixtures) and found 5 gaps, reported honestly
rather than patched around in the eval harness. The coordinator asked for
#1 and #2 (both severe) first, then the rest as time allowed — all five are
now fixed:

1. **SEVERE — nothing in production ever drove `parsing -> validating ->
   filed`.** Neither the webhook handler nor `scheduler_tick` called
   `run_parsing`/`run_validation`/`complete_filing` for a run past
   `document_received`; a real inbound COI would stall forever. Fixed with
   both halves the coordinator offered: (a) a new
   `app/orchestration/runner.py::process_inbound_document_to_terminal` /
   `drive_to_terminal` that the webhook handler
   (`app/webhooks/resend_inbound.py`) now calls, synchronously cascading
   `document_received -> parsing -> validating -> filed -> monitoring` (or
   to whatever guard-determined state) from ONE webhook delivery; and (b)
   `scheduler_tick` now sweeps `parsing`/`validating`/`filed` too (not just
   `document_received` as before) as the crash-recovery safety net, using
   the SAME `drive_to_terminal` helper. Gracefully degrades (stays put,
   doesn't crash the sweep) when no extraction engine is configured.
   Regression tests: `tests/test_webhook_resend_inbound.py::
   test_full_cascade_reaches_monitoring_with_no_manual_intervention` (and
   the sibling failing-coverage test), `tests/test_scheduler.py::
   TestCrashRecoverySweeps`.
2. **SEVERE — `agent_events` never received `tool_call`/`llm_call` rows.**
   Every tool built `ToolOutput.events` per ADR 0004, but nothing in
   `app/orchestration/runner.py` ever captured `.events` off an awaited
   tool call. Fixed: a new `_persist_events()` helper, called at every one
   of the ~13 tool-call sites in `runner.py` (send_email x4,
   parse_document x2, write_coi_record, file_document,
   mark_task_complete, escalate_to_pm x2, draft_explanation) — inline in
   the same transaction for DB-only tools, a short follow-up transaction
   for tools with external side effects. Also fixed two calls whose return
   value (and thus events) was previously discarded outright
   (`complete_filing`'s `handled_notice` send,
   `resolve_needs_human_review`'s `revision_request` send). Regression
   tests: `tests/test_agent_events_tool_capture.py`.
3. **`complete_filing` had no automatic caller deriving `valid_from`/
   `valid_to`.** New `app/orchestration/runner.py::advance_from_filed`
   derives both from the current extraction's `policy_effective_date`/
   `policy_expiration_date` (falling back to the extraction's processed
   date if `policy_effective_date` is absent — validation_logic.py doesn't
   currently require it; flagged as a follow-up, not fixed, to avoid
   changing pass/fail semantics qa-evals-engineer's fixtures assert
   against) and fails safe (`errored`) rather than guess if
   `policy_expiration_date` is somehow missing. This is now the function
   `drive_to_terminal` calls when a run reaches `filed`. Regression tests:
   `tests/test_orchestration_filing_and_human_review.py::TestAdvanceFromFiled`.
4. **`write_coi_record` called `evaluate_validation()` without `as_of`**,
   silently defaulting to real wall-clock `date.today()` instead of a
   frozen/injected time — a latent fixture-rot timer. Fixed: `run_validation`
   now accepts `now` (matching `evaluate_expiry`/`send_first_outreach`/
   `check_followup_or_deadline`'s existing pattern) and threads it through
   `UpdateCoiRecordWriteInput.as_of`. Regression tests: `tests/test_tools.py::
   TestWriteUpdateCoiRecord::test_explicit_as_of_is_honored_not_wall_clock`,
   `tests/test_orchestration_document_pipeline.py::
   test_run_validation_honors_explicit_now_not_wall_clock`.
5. **`send_email` had no injectable transport** (low priority). Added an
   `EmailTransport` Protocol + `transport` parameter to
   `app/tools/send_email.py::send_email`, defaulting to the real
   `resend_client.send` — existing callers are unaffected. Regression test:
   `tests/test_tools.py::TestSendEmail::test_transport_is_injectable`.

## Known gaps / still open

- **`runs.llm_call_count` is modeled as a single run-level counter**, but
  ADR 0002's `MAX_LLM_PER_DOC` budget is per-document. Resolved by resetting
  the counter to 0 whenever a NEW `coi_document_id` enters `parsing` (see
  `app/tools/base.py`'s docstring and
  `app/orchestration/runner.py:advance_from_document_received`).
- **`send_email`/`parse_document` crash window:** these tools use a
  two-phase commit around their external call (reserve -> call -> complete)
  so a crash before the call never double-fires, but a crash AFTER the
  provider accepts the call and BEFORE `complete()` commits can still,
  in principle, cause a retry to re-send. Documented in
  `app/tools/send_email.py`'s docstring; not fully closed in this pass
  (would need a provider-side idempotency key, e.g. Resend supports one).
- **Supabase Storage not wired** — `app/storage.py`'s `DocumentStorage`
  Protocol is the seam; `LocalFilesystemStorage` is the dev/test
  implementation. No live Supabase project exists yet in this repo to
  point a real implementation at.
- **`escalate_to_pm`'s DB write vs. its PM-notice email** are not
  atomically consistent with each other if the CALLER's outer transaction
  later rolls back (rare; documented in `app/tools/escalate_to_pm.py`).
- **`evaluate_validation` does not require `policy_effective_date`** to be
  present (only checks "not yet effective" when it IS present) — a passing
  validation doesn't guarantee `advance_from_filed` has a real effective
  date to file with, hence its documented fallback. Worth tightening
  `validation_logic.py` in a future pass; not done here to avoid changing
  pass/fail semantics qa-evals-engineer's golden fixtures already assert
  against without coordinating that change with them first.
- **Scheduler sweep cost grows with total run count** (`scheduler_tick`
  enumerates every enabled org, then every run in each swept state, every
  tick). Fine at v1's single-demo-org scale; would need pagination/indexing
  attention before real multi-tenant volume.

## Fixed by security review (2026-07-18, Opus, blocking findings)

1. **Path traversal via inbound attachment filename.** `storage_path` was
   built directly from the raw, untrusted inbound filename
   (`f"{vendor_id}/{document_id}_{filename}"`); a filename like
   `../../../../tmp/evil.pdf` passed the (then-extension-only) guardrail and
   escaped `LocalFilesystemStorage`'s `base_dir` on write. Fixed two ways:
   `app/policy/file_guardrails.py::check_attachment` now rejects any
   filename containing a path separator, `..`, or NUL outright; independently,
   `app/orchestration/runner.py::handle_inbound_document` no longer derives
   the storage key from the filename AT ALL — it's `document_id` +
   guardrail-detected extension, with the original filename kept only as
   metadata (`coi_documents.original_filename`). Regression tests:
   `tests/test_file_guardrails.py`,
   `tests/test_orchestration_document_pipeline.py::
   test_handle_inbound_document_never_uses_raw_filename_in_storage_path`.
2. **Public webhook had no body-size cap and no rate limiting**, and the
   HMAC verification ran over a fully-buffered, unbounded body before any
   auth decision (pre-auth memory/CPU DoS). Fixed: `app/main.py` now reads
   the body incrementally via `request.stream()`, rejecting with 413 as soon
   as it exceeds `2x MAX_FILE_BYTES` — before any signature work — and a new
   in-process rate limiter (`app/policy/rate_limit.py`, 60 req/60s per
   client IP; # ASSUMPTION: single-instance only, needs a shared store like
   Redis for multi-instance deployment) rejects with 429 before that.
   Verified against the actual running app (`uvicorn` + `curl`), not just
   the test client. Regression tests: `tests/test_main_app.py`.
3. **Document-download route served untrusted content with an
   attacker-controlled Content-Type, inline, with no nosniff** (BLOCK,
   found after the CRLF-injection fix above was already approved). The
   CRLF fix stripped bad characters from `coi_documents.content_type` but
   didn't constrain the VALUE — that column is the inbound webhook's
   attacker-supplied MIME string, stored verbatim, and the ingest guardrail
   only checks a magic-byte PREFIX (a PDF-polyglot containing HTML/JS
   passes it). Combined with `Content-Disposition: inline` and no
   `X-Content-Type-Options`, a vendor could get a PM's (or the frontend's
   embedded `DocumentRef.url`) browser to render/execute a malicious
   payload — CLAUDE.md's "malicious COI -> exfiltrate data" highest-risk
   surface. Fixed with all three of the reviewer's suggested mitigations,
   not just two: `app/api/reads.py::_safe_media_type` now derives the
   response media type SOLELY from a fixed allowlist keyed on the
   guardrail-detected type recoverable from `storage_path`'s extension
   (never from `content_type`); every response carries
   `X-Content-Type-Options: nosniff`; and these evidence files are served
   as `Content-Disposition: attachment`, never `inline`. Regression test:
   `tests/test_api_reads.py::TestDocumentDownload::
   test_download_ignores_attacker_controlled_content_type` (a PDF-polyglot
   with a spoofed `text/html` content_type, asserting the response never
   leaks "html", resolves to `application/pdf`, carries nosniff, and is an
   attachment).

Every one of the above is also marked `# ASSUMPTION:` or a gap note inline
at its source — this section is a map to them, not a substitute for reading
the code.
