"""Real implementation of `harness.pipeline_adapter.PipelineUnderTest`,
wired against the actual backend orchestration runner
(`backend/app/orchestration/runner.py`) over the SAME Dockerized Postgres
backend-engineer's own test suite uses (`backend/docker-compose.yml`).

This is the thin real implementation `pipeline_adapter.py`'s module
docstring asked for once backend's shape existed — the harness's original
`PipelineDependencies`/`PipelineUnderTest` Protocol (a bag-of-deps object
with `llm_client`/`email_client`/`requirements_retriever`/`now`) turned out
NOT to match backend's actual dependency-injection pattern:

  - `run_parsing(org_id, run_id, *, engine: ExtractionEngine, storage=...)`
    takes an `ExtractionEngine` (`.extract(document_bytes=, content_type=,
    prompt_id=, attempt_no=) -> ExtractionEngineResult`), not the harness's
    originally-proposed `MockLLMClient` (`.complete(prompt_id=,
    prompt_text=, **kwargs)`). These are different shapes. Per the
    backend-engineer's own README ("Interface left for agent-engineer"),
    the intended test-double seam IS a fake `ExtractionEngine` — exactly
    backend's own `FakeEngine` in
    `backend/tests/test_orchestration_document_pipeline.py`. `_GoldenFixtureEngine`
    below is that same pattern, scripted per golden fixture instead of per
    unit test.
  - Nothing in the runner takes an injectable email client at all —
    `app/tools/send_email.py` always calls `app.tools.resend_client.send()`,
    which safely SIMULATES a send (fake provider id, no network call) when
    `RESEND_API_KEY` is unset (the default, and always the case here). So
    Resend is never live from this suite either way, just via a different
    mechanism than the harness originally proposed (see "Known gaps" below).
  - Nothing in the runner takes an injectable clock — `run_parsing`/
    `run_validation` don't accept a `now`. Deterministic date freezing
    (`fixture.now`) is therefore NOT actually exercised end-to-end for the
    validating step; see the KNOWN GAP note below.

`# ASSUMPTION: PipelineDependencies.llm_client` / `.email_client` / `.now`
are consequently UNUSED by this real implementation (deliberately; there is
no seam to plug them into in the current backend build) — they remain
accepted (for Protocol compatibility with `pipeline_adapter.PipelineUnderTest`)
but ignored. Flagged to the tech lead rather than silently worked around:
the harness's original DI seam guess doesn't match reality on these three
points; `PipelineDependencies` should probably be slimmed down (or backend
should grow the seams) once this is triaged.

======================================================================
KNOWN GAPS FOUND WHILE WIRING THIS (reported, not fixed — do not patch
backend/ to make fixtures pass; these are real findings for backend-engineer
/ architect) :
======================================================================

1. **`agent_events` never receives `tool_call` / `llm_call` rows.** Every
   tool (`parse_document`, `update_coi_record` write mode, `file_document`,
   `mark_task_complete`, `send_email`, `escalate_to_pm`'s own event) builds
   and RETURNS `ToolOutput.events: list[PendingEvent]` exactly per ADR 0004's
   "tools never write agent_events directly — they return these, and the
   caller ... persists them in the same transaction". But
   `app/orchestration/runner.py` never captures `.events` off any tool
   result it awaits (`run_parsing`'s classify/extract results,
   `run_validation`'s `write_result`, `complete_filing`'s `file_result`/
   `complete_result`, `_escalate`/`_needs_human_review`'s
   `escalate_to_pm(...)` call) — confirmed by
   `grep -rn "[.]events" app/` finding exactly one consumer
   (`escalate_to_pm.py` aggregating `send_email`'s events into its OWN
   return, which is itself then discarded by every caller). In the current
   build, `agent_events` therefore only ever contains `state_transition`
   (via `_transition`), `guardrail_trip` (only the policy/budget pre-check
   denials via `_record_guardrail_trip` — NOT `parse_document`'s
   classify-rejection or `mark_task_complete`'s precondition-failure
   PendingEvents, which are also silently dropped), `error` (via
   `_errored`), and `human_intervention` events. This directly undercuts
   CLAUDE.md's Observability promise ("Every state transition, tool call,
   LLM call (prompt hash, model, tokens, cost, latency) ... writes to
   agent_events") and the trace-timeline UI (key screen 3) would currently
   render an incomplete trace with no tool-call/LLM-cost rows at all.
   WORKAROUND HERE (not a fix): this adapter reconstructs `ToolCallRecord`s
   from `tool_invocations` (the idempotency ledger — genuinely populated for
   every side-effecting tool except `escalate_to_pm`, which isn't
   idempotency-ledger-backed by design) plus the `escalations` table for
   `escalate_to_pm` itself. This is still 100% REAL persisted state, not a
   mock — just read from a different table than `agent_events` because the
   intended one is missing these rows. Reported to backend-engineer/architect.

2. **No scheduler/webhook path drives `parsing` -> `validating` -> `filed`
   -> `monitoring`.** `app/orchestration/scheduler.py::scheduler_tick` only
   sweeps `monitoring`, `renewal_due_soon`, `awaiting_vendor_response`
   wakeups, and a `document_received` crash-recovery sweep
   (`advance_from_document_received`). Once a document reaches `parsing`,
   NOTHING in production calls `run_parsing`, `run_validation`, or
   `complete_filing` — only backend's own white-box tests
   (`backend/tests/test_orchestration_document_pipeline.py`) call them
   directly. A real inbound COI would sit in `parsing` forever. This
   adapter calls them directly too (same as backend's tests), which is
   necessary to exercise the pipeline at all, but that necessity is itself
   the finding: this is a real orchestration gap, not a harness-only
   concern.

3. **`complete_filing(org_id, run_id, *, valid_from, valid_to)` has no
   automatic caller that derives `valid_from`/`valid_to` from the
   extraction.** Combined with (2), nothing in production ever calls this
   function with real dates. This adapter derives them from the run's
   current `coi_extractions` row (`policy_effective_date`/
   `policy_expiration_date`), which is the obviously-intended source.

4. **`app/tools/update_coi_record.py::write_coi_record` calls
   `evaluate_validation(...)` WITHOUT an `as_of` argument**, so the
   deterministic pass/fail comparison silently uses the REAL wall-clock
   `date.today()` (`validation_logic.py`'s `as_of = as_of or date.today()`)
   rather than the run's/fixture's frozen `now`. Every golden fixture here
   hardcodes `now = date(2026, 7, 18)` and this suite happens to be run on
   that real calendar date, so it works today — but this is a latent
   fixture-rot timer, not a coincidence to rely on: `expired_01_old_cert_
   plumbing` and `future_dated_02_pestaway` in particular encode "is this
   date in the past/future RELATIVE TO NOW" assertions that will silently
   drift as real wall-clock time moves past the fixtures' hardcoded dates
   (e.g. `clean_01`'s `valid_to=2027-07-01` will itself start failing
   validation once real "today" passes mid-2027). Reported to
   backend-engineer: `write_coi_record` should thread a caller-supplied
   `as_of` (from `ToolContext`/orchestration's own now) through to
   `evaluate_validation`, the same way `evaluate_expiry`/
   `send_first_outreach`/`check_followup_or_deadline` already accept `now`.

5. **`send_email` has no injectable transport** — see the module-docstring
   note above. Functionally safe for tests (Resend is never live), but it
   means `PipelineDependencies.email_client` (`MockEmailClient`) is
   completely bypassed by the real pipeline. Concretely: the
   `injection_03_exfiltration_attempt` fixture's extra assertion in
   `test_golden_documents.py` (`mock_email_client.sent` must not contain the
   injected address) is VACUOUSLY true against the real pipeline — nothing
   ever populates `mock_email_client.sent`, so that specific adversarial
   check is not exercising anything real right now. Not fixed here (would
   mean editing `test_golden_documents.py`'s fixture-specific assertion
   beyond this task's stated scope, or backend adding a DI seam to
   `send_email` — either is a call for the tech lead, not a unilateral
   change); flagged clearly instead. The base trajectory assertions
   (final_state, forbidden_states, forbidden_tool_calls) for that fixture
   still exercise real backend code and are meaningful.

None of the above were patched — per this task's rules, production source
in `backend/` is not modified to make a fixture pass. Findings are reported
to the tech lead / backend-engineer instead.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# --- seam: make backend's `app` package importable regardless of the cwd
# the eval suite is invoked from (repo root, per tests/evals/pytest.ini's
# own docstring) -----------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import asyncpg  # noqa: E402

from tests.evals.contracts.state_machine import (  # noqa: E402
    EscalationRecord,
    GuardrailTrip,
    ReasonCode,
    RunState as EvalRunState,
    RunTrajectory,
    StateTransition,
    TERMINAL_STATES,
    ToolCallRecord,
    Trigger,
)
from tests.evals.fixtures.golden_manifest import GoldenDocumentFixture  # noqa: E402
from tests.evals.fixtures.org_context import base_org  # noqa: E402
from tests.evals.harness.pipeline_adapter import PipelineDependencies  # noqa: E402

from app.db import init_pools, org_scoped_tx  # noqa: E402
from app.ids import uuid7  # noqa: E402
from app.models.coi_fields import ExtractedCoiFields, ExtractedCoverageLine  # noqa: E402
from app.models.enums import CoverageType as BackendCoverageType, RunState as BackendRunState  # noqa: E402
from app.orchestration.runner import (  # noqa: E402
    complete_filing,
    handle_inbound_document,
    run_parsing,
    run_validation,
)
from app.retrieval import entity_repo, run_repo  # noqa: E402
from app.storage import LocalFilesystemStorage  # noqa: E402
from app.tools.parse_document import ExtractionEngineResult  # noqa: E402

_ADMIN_DSN = "postgresql://postgres:postgres@localhost:55432/rowan"

# Reason codes that show up verbatim as `escalations.reason_code` /
# `agent_events.payload["guardrail"]` string values in production and map
# 1:1 onto the harness's closed ReasonCode vocabulary (contracts/
# state_machine.py). Deliberately NOT exhaustive of every guardrail_name
# app/policy/guardrails.py can produce (e.g. budget/allowlist denial names
# aren't in the harness's ReasonCode enum at all) — unmapped codes are
# skipped rather than guessed, matching this suite's "never guess" ethos.
_REASON_CODE_MAP: dict[str, ReasonCode] = {rc.value: rc for rc in ReasonCode}


# ---------------------------------------------------------------------------
# Event loop: reused across the whole pytest session (NOT asyncio.run() per
# call) so `app.db`'s module-level asyncpg pools stay bound to a single,
# still-open loop across all 18 fixture invocations. asyncio.run() would
# create+close a fresh loop per call, orphaning the pool after fixture #1.
# ---------------------------------------------------------------------------
_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop


def run_document_pipeline(fixture: GoldenDocumentFixture, deps: PipelineDependencies) -> RunTrajectory:
    """Entry point matching `harness.pipeline_adapter.PipelineUnderTest`."""
    loop = _get_loop()
    return loop.run_until_complete(_run_pipeline_async(fixture, deps))


async def _run_pipeline_async(fixture: GoldenDocumentFixture, deps: PipelineDependencies) -> RunTrajectory:
    await init_pools()
    admin_conn = await asyncpg.connect(_ADMIN_DSN)
    try:
        ids = await _provision(admin_conn, fixture)
        storage = LocalFilesystemStorage(base_dir=str(_storage_dir(fixture)))
        engine = _GoldenFixtureEngine(fixture)

        await _drive(ids.org_id, ids.run_id, fixture=fixture, engine=engine, storage=storage)

        return await _assemble_trajectory(admin_conn, org_id=ids.org_id, run_id=ids.run_id)
    finally:
        await admin_conn.close()


def _storage_dir(fixture: GoldenDocumentFixture) -> Path:
    import tempfile

    return Path(tempfile.gettempdir()) / "rowan-eval-storage" / fixture.id


# ---------------------------------------------------------------------------
# Provisioning: fresh org/property/vendor/compliance_requirements/
# vendor_coverage_requirements/user + a run pre-seeded in
# `awaiting_vendor_response`, mirroring backend's own `org_and_vendor`/
# `make_run` test fixtures (backend/tests/conftest.py) exactly — a fresh
# org per fixture invocation avoids any PK/unique-constraint collision
# across repeated runs against the same accumulating local Postgres
# (documented gotcha in backend/README.md).
# ---------------------------------------------------------------------------


@dataclass
class _ProvisionedIds:
    org_id: uuid.UUID
    vendor_id: uuid.UUID
    run_id: uuid.UUID


async def _provision(conn: asyncpg.Connection, fixture: GoldenDocumentFixture) -> _ProvisionedIds:
    org_id = uuid7()
    property_id = uuid7()
    vendor_id = uuid7()
    run_id = uuid7()

    await conn.execute(
        "insert into organizations (id, name, agent_enabled) values ($1, $2, true)",
        org_id,
        f"Eval Org [{fixture.id}]",
    )

    prop = fixture.property
    await conn.execute(
        """
        insert into properties (
            id, organization_id, name, line1, city, state, postal_code, hoa_name, property_type
        ) values ($1,$2,$3,'1 Eval St',$4,$5,'00000',$6,$7)
        """,
        property_id,
        org_id,
        prop.name,
        prop.city,
        prop.state,
        prop.hoa_name,
        prop.property_type.value,
    )

    vendor = fixture.vendor
    await conn.execute(
        """
        insert into vendors (id, organization_id, name, primary_email, vendor_role, status, primary_property_id)
        values ($1,$2,$3,$4,$5,'active',$6)
        """,
        vendor_id,
        org_id,
        vendor.name,
        vendor.primary_email,
        vendor.vendor_role.value,
        property_id,
    )

    await conn.execute(
        "insert into users (id, organization_id, auth_user_id, email, role) values ($1,$2,$3,$4,'owner')",
        uuid7(),
        org_id,
        uuid.uuid4(),
        "pm@eval.rowan.test",
    )

    await _provision_requirements(conn, org_id=org_id, vendor_id=vendor_id, fixture=fixture)

    reply_token = f"eval_{run_id}"
    await conn.execute(
        """
        insert into runs (
            id, organization_id, vendor_id, state, status, trigger, due_date,
            reply_token, reply_token_expires_at, budget_cost_cap_cents
        ) values ($1,$2,$3,'awaiting_vendor_response','active','renewal_due',$4,$5,$6,200)
        """,
        run_id,
        org_id,
        vendor_id,
        fixture.now,
        reply_token,
        datetime.now(timezone.utc) + timedelta(days=30),
    )

    return _ProvisionedIds(org_id=org_id, vendor_id=vendor_id, run_id=run_id)


async def _provision_requirements(
    conn: asyncpg.Connection, *, org_id: uuid.UUID, vendor_id: uuid.UUID, fixture: GoldenDocumentFixture
) -> None:
    """Materializes `compliance_requirements` (KB rows) + `vendor_coverage_
    requirements` directly, mirroring what ADR 0005 says onboarding does via
    the retriever — done directly here (not via `V1DeterministicRetriever`)
    because this is fixture/test SETUP, exactly like backend's own
    `org_and_vendor` conftest fixture.

    Fixture KB rows (`base_org.COMPLIANCE_REQUIREMENTS_KB`) carry
    deterministic `stable_id()` UUIDs that are the SAME across every
    fixture/test run (by design, for fixture cross-referencing) — but
    `compliance_requirements.id` is a globally unique PK with no org
    scoping, and many fixtures share the same logical KB row (e.g. most
    Oakland-property fixtures reference `CR_OAKLAND_GL`). Reusing the
    fixture's `stable_id()` value as the literal DB primary key would
    collide the moment a second fixture in the same pytest session tried to
    insert the "same" row. So: mint a FRESH real uuid7() per (fixture run,
    logical KB row) here, insert real content under that fresh id, and use
    that same fresh id when materializing `vendor_coverage_requirements.
    source_compliance_requirement_id` — the CONTENT matches the fixture's
    intended KB row exactly; only the literal primary key differs run to run.
    """
    kb_by_logical_id = {r.id: r for r in base_org.COMPLIANCE_REQUIREMENTS_KB}
    minted: dict[uuid.UUID, uuid.UUID] = {}

    for vcr in fixture.vendor_coverage_requirements:
        source_id = vcr.source_compliance_requirement_id
        if source_id is None or source_id in minted:
            continue
        kb = kb_by_logical_id.get(source_id)
        if kb is None:
            raise AssertionError(
                f"{fixture.id}: vendor_coverage_requirements references KB id {source_id} "
                f"which is not in base_org.COMPLIANCE_REQUIREMENTS_KB"
            )
        jurisdiction = base_org.KB_ROW_JURISDICTION[source_id]
        role = base_org.KB_ROW_VENDOR_ROLE.get(source_id)
        fresh_id = uuid7()
        await conn.execute(
            """
            insert into compliance_requirements (
                id, organization_id, jurisdiction_state, jurisdiction_city, jurisdiction_hoa,
                vendor_role, coverage_type, min_each_occurrence, min_aggregate,
                requires_additional_insured, requires_waiver_of_subrogation,
                requires_primary_noncontributory, source_citation, source_url,
                last_verified_at, active
            ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,true)
            """,
            fresh_id,
            org_id,
            jurisdiction["state"],
            jurisdiction["city"],
            jurisdiction["hoa"],
            role.value if role else None,
            kb.coverage_type.value,
            kb.min_each_occurrence,
            kb.min_aggregate,
            kb.requires_additional_insured,
            kb.requires_waiver_of_subrogation,
            kb.requires_primary_noncontributory,
            kb.source_citation,
            kb.source_url,
            kb.last_verified_at,
        )
        minted[source_id] = fresh_id

    for vcr in fixture.vendor_coverage_requirements:
        real_source_id = (
            minted.get(vcr.source_compliance_requirement_id)
            if vcr.source_compliance_requirement_id is not None
            else None
        )
        await conn.execute(
            """
            insert into vendor_coverage_requirements (
                id, organization_id, vendor_id, coverage_type, min_each_occurrence, min_aggregate,
                requires_additional_insured, requires_waiver_of_subrogation,
                requires_primary_noncontributory, source_compliance_requirement_id, confirmed_by_pm
            ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,true)
            """,
            uuid7(),
            org_id,
            vendor_id,
            vcr.coverage_type.value,
            vcr.min_each_occurrence,
            vcr.min_aggregate,
            vcr.requires_additional_insured,
            vcr.requires_waiver_of_subrogation,
            vcr.requires_primary_noncontributory,
            real_source_id,
        )


# ---------------------------------------------------------------------------
# Driving the real state machine. Mirrors backend's own white-box test
# pattern (backend/tests/test_orchestration_document_pipeline.py) — direct
# calls to handle_inbound_document / run_parsing / run_validation /
# complete_filing, because (per the module docstring's Known Gap #2) nothing
# in production currently chains these automatically either.
# ---------------------------------------------------------------------------


def _document_bytes(fixture: GoldenDocumentFixture) -> bytes:
    text = fixture.document_path.read_text(encoding="utf-8", errors="replace")
    # Real PDF magic header so app.policy.file_guardrails.check_attachment's
    # type-sniffing passes, with the fixture's actual text as payload after
    # it (harmless in mock mode since _GoldenFixtureEngine never reads
    # document_bytes; kept for parity with a future real-Claude-mode reuse).
    return b"%PDF-1.4\n" + text.encode("utf-8", errors="replace")


async def _drive(
    org_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    fixture: GoldenDocumentFixture,
    engine: "_GoldenFixtureEngine",
    storage: LocalFilesystemStorage,
) -> None:
    await handle_inbound_document(
        org_id,
        run_id,
        filename="coi.pdf",
        data=_document_bytes(fixture),
        content_type="application/pdf",
        storage=storage,
    )

    run_row = await _get_run(org_id, run_id)
    if run_row is not None and run_row.state == BackendRunState.parsing:
        await run_parsing(org_id, run_id, engine=engine, storage=storage)
        run_row = await _get_run(org_id, run_id)

    if run_row is not None and run_row.state == BackendRunState.validating:
        await run_validation(org_id, run_id)
        run_row = await _get_run(org_id, run_id)

    if run_row is not None and run_row.state == BackendRunState.filed:
        valid_from, valid_to = await _dates_from_current_extraction(org_id, run_row.coi_document_id)
        if valid_from is not None and valid_to is not None:
            await complete_filing(org_id, run_id, valid_from=valid_from, valid_to=valid_to)
        # If dates are missing, leave the run at `filed` rather than guess —
        # matches this suite's own "never guess" rule; final_state will
        # correctly still read as FILED (see _terminal_state).


async def _get_run(org_id: uuid.UUID, run_id: uuid.UUID):
    async with org_scoped_tx(org_id) as conn:
        return await run_repo.get_run(conn, run_id)


async def _dates_from_current_extraction(
    org_id: uuid.UUID, coi_document_id: Optional[uuid.UUID]
) -> tuple[Optional[date], Optional[date]]:
    if coi_document_id is None:
        return None, None
    async with org_scoped_tx(org_id) as conn:
        extraction = await entity_repo.get_current_extraction(conn, coi_document_id)
    if extraction is None:
        return None, None
    extracted = extraction.extracted
    vf = extracted.get("policy_effective_date")
    vt = extracted.get("policy_expiration_date")
    return (
        date.fromisoformat(vf) if vf else None,
        date.fromisoformat(vt) if vt else None,
    )


# ---------------------------------------------------------------------------
# The mocked LLM: a fake ExtractionEngine scripted per golden fixture,
# same seam backend-engineer left for agent-engineer
# (app/tools/parse_document.py's ExtractionEngine Protocol) and the same
# shape as backend's own FakeEngine test double
# (backend/tests/test_orchestration_document_pipeline.py) — never calls
# Claude, deterministic, offline. Two sub-passes (classify, extract) per
# ADR 0004's amendment; `run_parsing` calls this once per prompt_id.
# ---------------------------------------------------------------------------


def _flat_dict_to_extracted_coi_fields(expected: dict[str, Any]) -> ExtractedCoiFields:
    """Inverse of metrics/field_accuracy.py's flat dotted-key shape ->
    the real ExtractedCoiFields schema `parse_document` persists. Fixtures'
    `expected_extraction` IS the ground truth the golden document is meant
    to contain, so scripting the mock extract-pass to return exactly this
    (at high confidence) is the intended "deterministic, fixture-appropriate
    extraction result" per this task's brief — NOT a claim about real
    extraction accuracy (that is real-Claude-mode's job, gated separately).
    """
    insured_name = expected.get("insured_name")
    valid_from = expected.get("policy.valid_from")
    valid_to = expected.get("policy.valid_to")

    by_coverage: dict[str, dict[str, Any]] = {}
    for key, value in expected.items():
        if not key.startswith("coverage."):
            continue
        _, coverage_type, field_name = key.split(".", 2)
        by_coverage.setdefault(coverage_type, {})[field_name] = value

    lines = [
        ExtractedCoverageLine(
            coverage_type=BackendCoverageType(coverage_type),
            each_occurrence=fields.get("each_occurrence"),
            aggregate=fields.get("aggregate"),
            additional_insured=fields.get("additional_insured"),
            waiver_of_subrogation=fields.get("waiver_of_subrogation"),
            primary_noncontributory=fields.get("primary_noncontributory"),
            confidence=0.95,
        )
        for coverage_type, fields in by_coverage.items()
    ]

    return ExtractedCoiFields(
        insured_name_on_certificate=insured_name,
        policy_effective_date=date.fromisoformat(valid_from) if valid_from else None,
        policy_expiration_date=date.fromisoformat(valid_to) if valid_to else None,
        coverage_lines=lines,
        overall_confidence=0.95,
    )


@dataclass
class _GoldenFixtureEngine:
    """Matches `app.tools.parse_document.ExtractionEngine` Protocol."""

    fixture: GoldenDocumentFixture

    async def extract(
        self, *, document_bytes: bytes, content_type: str, prompt_id: str, attempt_no: int
    ) -> ExtractionEngineResult:
        if prompt_id == "classify":
            return self._classify()
        return self._extract()

    def _classify(self) -> ExtractionEngineResult:
        # garbage_01_corrupted_scan is the ONLY fixture whose classify pass
        # must reject the document outright (is_coi=False) — see
        # golden_manifest.py's updated expected_trajectory + this task's
        # garbage_01 fix note. Every other fixture (including garbage_02,
        # which is COI-shaped but illegible) clears classification.
        is_coi = self.fixture.id != "garbage_01_corrupted_scan"
        confidence = 0.95 if is_coi else 0.05
        return ExtractionEngineResult(
            extracted=ExtractedCoiFields(overall_confidence=confidence),
            field_confidence={},
            model="mock-classify-v1",
            prompt_hash="mock-classify",
            input_tokens=1,
            output_tokens=1,
            cost_cents=0,
            is_coi=is_coi,
            document_type="certificate_of_insurance" if is_coi else None,
        )

    def _extract(self) -> ExtractionEngineResult:
        if self.fixture.id == "garbage_02_low_confidence_fax":
            # COI-shaped but illegible: classify passed, extract must not.
            return ExtractionEngineResult(
                extracted=ExtractedCoiFields(
                    overall_confidence=0.30, notes="Fixture-scripted: illegible fax, sub-threshold confidence."
                ),
                field_confidence={},
                model="mock-extract-v1",
                prompt_hash="mock-extract",
                input_tokens=5,
                output_tokens=5,
                cost_cents=1,
            )
        fields = _flat_dict_to_extracted_coi_fields(self.fixture.expected_extraction or {})
        return ExtractionEngineResult(
            extracted=fields,
            field_confidence={},
            model="mock-extract-v1",
            prompt_hash="mock-extract",
            input_tokens=20,
            output_tokens=20,
            cost_cents=1,
        )


# ---------------------------------------------------------------------------
# Assembling RunTrajectory from real persisted state: `agent_events` for
# state_transition/guardrail_trip, `escalations` for escalation records,
# `tool_invocations` for tool calls (see Known Gap #1 above for why
# tool_invocations rather than agent_events for the latter — it's still 100%
# real DB state, just a different table than the intended one), and
# `coi_extractions` (via entity_repo.get_current_extraction — NEVER a raw
# query — see this task's "empty-coverage classify-pass extraction record"
# note: parse_document now writes a coi_extractions row for the classify
# pass too (empty coverage_lines), and get_current_extraction correctly
# resolves to the LATER, `is_current=true` extract-pass row, which is why
# every read of extracted fields in this module goes through that repo
# function and never a bare `select ... from coi_extractions`).
# ---------------------------------------------------------------------------


def _loads(value: Any) -> Any:
    import json

    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    return value


_TRIGGER_BY_TRANSITION: dict[tuple[str, str], Trigger] = {
    ("awaiting_vendor_response", "document_received"): Trigger.WEBHOOK,
    ("needs_human_review", "filed"): Trigger.HUMAN,
    ("needs_human_review", "awaiting_vendor_response"): Trigger.HUMAN,
    ("needs_human_review", "escalated_to_pm"): Trigger.HUMAN,
    ("escalated_to_pm", "monitoring"): Trigger.HUMAN,
    ("escalated_to_pm", "awaiting_vendor_response"): Trigger.HUMAN,
}


def _infer_trigger(from_state: Optional[str], to_state: str) -> Trigger:
    if from_state is None:
        return Trigger.TOOL
    return _TRIGGER_BY_TRANSITION.get((from_state, to_state), Trigger.TOOL)


def _map_reason_code(raw: Optional[str]) -> Optional[ReasonCode]:
    if raw is None:
        return None
    return _REASON_CODE_MAP.get(raw)


async def _derive_completion_basis(conn: asyncpg.Connection, run_id: uuid.UUID) -> Optional[str]:
    """Recomputes the SAME basis `app.orchestration.runner.complete_filing`
    used, from real persisted state (validation result/faithfulness,
    approved escalation) — MarkTaskCompleteData itself doesn't carry
    `completion_basis` in its persisted response (see Known Gap #1's
    sibling note in the module docstring: this field simply isn't in the
    tool's own output schema), so this is a legitimate independent
    reconstruction from the same tables the real precondition check reads,
    not a guess.
    """
    run_row = await run_repo.get_run(conn, run_id)
    if run_row is None or run_row.coi_document_id is None:
        return None
    extraction = await entity_repo.get_current_extraction(conn, run_row.coi_document_id)
    if extraction is None:
        return None
    validation = await entity_repo.get_latest_validation_for_extraction(conn, extraction.id)
    if validation is None:
        return None
    if validation.result.value == "pass" and validation.faithfulness_ok:
        return "validation_passed"
    approved = await entity_repo.get_latest_approved_escalation(conn, run_id)
    if approved is not None:
        return "human_approved"
    return None


def _build_tool_call(row: asyncpg.Record, completion_basis: Optional[str]) -> ToolCallRecord:
    tool_name = row["tool_name"]
    response = _loads(row["response"]) or {}
    error = _loads(row["error"]) or {}
    data = dict(response)

    status = "ok" if row["status"] == "succeeded" else "failed"
    if error.get("reason") == "precondition_not_met":
        status = "denied"

    if tool_name == "update_coi_record" and isinstance(data.get("flags"), list):
        # Real stored shape is list[dict] (code/severity/message per
        # app.tools.validation_logic.ValidationOutcome.flags); trajectory_
        # assert.py's expected_validation_flags check expects an iterable of
        # bare code strings (`actual_flags.update(c.data.get("flags", []))`).
        data["flags"] = [f.get("code") for f in data["flags"] if isinstance(f, dict) and f.get("code")]

    if tool_name == "mark_task_complete" and status == "ok" and completion_basis is not None:
        data["completion_basis"] = completion_basis

    return ToolCallRecord(tool_name=tool_name, status=status, idempotent_replay=False, data=data)


async def _flatten_current_extraction(conn: asyncpg.Connection, run_row) -> Optional[dict[str, Any]]:
    if run_row is None or run_row.coi_document_id is None:
        return None
    extraction = await entity_repo.get_current_extraction(conn, run_row.coi_document_id)
    if extraction is None:
        return None
    extracted = extraction.extracted
    flat: dict[str, Any] = {}
    if extracted.get("insured_name_on_certificate") is not None:
        flat["insured_name"] = extracted["insured_name_on_certificate"]
    if extracted.get("policy_effective_date") is not None:
        flat["policy.valid_from"] = extracted["policy_effective_date"]
    if extracted.get("policy_expiration_date") is not None:
        flat["policy.valid_to"] = extracted["policy_expiration_date"]
    for line in extracted.get("coverage_lines", []) or []:
        cov = line.get("coverage_type")
        for field_name in (
            "each_occurrence",
            "aggregate",
            "additional_insured",
            "waiver_of_subrogation",
            "primary_noncontributory",
        ):
            if line.get(field_name) is not None:
                flat[f"coverage.{cov}.{field_name}"] = line[field_name]
    return flat


def _terminal_state(states: list[StateTransition]) -> EvalRunState:
    for t in states:
        if t.to_state in TERMINAL_STATES:
            return t.to_state
    # No terminal-for-cycle state reached (e.g. run stalled mid-pipeline) —
    # report the last observed state rather than guess; assert_trajectory
    # will correctly fail this against whatever the fixture expected.
    return states[-1].to_state


async def _assemble_trajectory(conn: asyncpg.Connection, *, org_id: uuid.UUID, run_id: uuid.UUID) -> RunTrajectory:
    run_row = await run_repo.get_run(conn, run_id)

    event_rows = await conn.fetch(
        """
        select event_type, name, severity, from_state, to_state, payload, created_at
        from agent_events where run_id = $1 order by created_at asc, id asc
        """,
        run_id,
    )

    states: list[StateTransition] = []
    guardrail_trips: list[GuardrailTrip] = []
    for row in event_rows:
        payload = _loads(row["payload"]) or {}
        if row["event_type"] == "state_transition":
            states.append(
                StateTransition(
                    from_state=EvalRunState(row["from_state"]) if row["from_state"] else None,
                    to_state=EvalRunState(row["to_state"]),
                    trigger=_infer_trigger(row["from_state"], row["to_state"]),
                    guard=payload.get("guard") or row["name"],
                )
            )
        elif row["event_type"] == "guardrail_trip":
            code = payload.get("guardrail") or payload.get("reason")
            reason = _map_reason_code(code)
            if reason is not None:
                guardrail_trips.append(GuardrailTrip(reason_code=reason, severity=row["severity"], detail=payload))

    escalation_rows = await conn.fetch(
        """
        select kind, reason_code, status, resolution
        from escalations where run_id = $1 order by created_at asc
        """,
        run_id,
    )
    escalations: list[EscalationRecord] = []
    for row in escalation_rows:
        reason = _map_reason_code(row["reason_code"])
        if reason is None:
            continue
        escalations.append(EscalationRecord(kind=row["kind"], reason_code=reason, resolution=row["resolution"]))
        # See Known Gap #1: escalate_to_pm's own PendingEvent (which would
        # normally be a guardrail_trip/note agent_events row) is dropped by
        # every caller, so the `escalations` table itself is the real
        # source of truth for "this condition tripped" here.
        guardrail_trips.append(
            GuardrailTrip(reason_code=reason, severity="warn", detail={"escalation_reason_code": row["reason_code"]})
        )

    completion_basis = await _derive_completion_basis(conn, run_id)

    inv_rows = await conn.fetch(
        """
        select tool_name, status, response, error, created_at
        from tool_invocations where run_id = $1 order by created_at asc, id asc
        """,
        run_id,
    )
    tool_calls = [_build_tool_call(row, completion_basis) for row in inv_rows]
    for row in escalation_rows:
        tool_calls.append(
            ToolCallRecord(
                tool_name="escalate_to_pm",
                status="ok",
                data={"kind": row["kind"], "reason_code": row["reason_code"]},
            )
        )

    extracted_fields = await _flatten_current_extraction(conn, run_row)

    if not states:
        # Defensive: should not happen for any of these fixtures (every one
        # enters via a valid inbound attachment), but fail with a clear
        # final_state rather than raise inside RunTrajectory construction.
        final_state = EvalRunState.DOCUMENT_RECEIVED
    else:
        final_state = _terminal_state(states)

    return RunTrajectory(
        run_id=str(run_id),
        states=states,
        guardrail_trips=guardrail_trips,
        escalations=escalations,
        tool_calls=tool_calls,
        final_state=final_state,
        extracted_fields=extracted_fields,
    )
