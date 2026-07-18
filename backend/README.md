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
  main.py                    FastAPI app: /health, /webhooks/resend/inbound, /internal/scheduler/tick
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

Every one of the above is also marked `# ASSUMPTION:` or a gap note inline
at its source — this section is a map to them, not a substitute for reading
the code.
