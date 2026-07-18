"""The orchestration runner (layer 2, ADR 0002). This IS the planner —
there is no free-roaming agent loop. Every function here corresponds to one
guarded transition (or a small cascade of tool-triggered transitions) from
the state machine spec. The LLM is invoked only inside `parse_document` and
(later) a drafting call in `run_validation` — never here; this module only
decides "given the current persisted state and a trigger, what allowlisted
action, if any, fires next."

Crash-recoverability: every public function here is safe to call twice for
the same run (webhook replay, scheduler double-tick, retried HTTP request).
Each one re-reads current state, re-evaluates the guard, and if the guard
no longer holds (because a previous, possibly-crashed attempt already made
progress), it is a no-op — never a duplicate transition, never a duplicate
side effect (side effects are only ever reached through the idempotent
tools layer). See app/retrieval/run_repo.py's module docstring for the CAS
mechanism this all rests on.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.db import org_scoped_tx
from app.ids import uuid7
from app.models.enums import EventSeverity, EventType, RunState, RunStatus
from app.models.tool_contracts import ToolContext
from app.observability.events import write_event
from app.orchestration.constants import RunConstants, resolve_constants
from app.policy.actions import Action
from app.policy.guardrails import PolicyDecision, check_action, check_budget, check_kill_switches
from app.retrieval import entity_repo, run_repo
from app.retrieval.models import OrganizationRow, RunRow, VendorRow
from app.tools.base import budget_snapshot
from app.tools.escalate_to_pm import EscalateToPmInput, escalate_to_pm
from app.tools.file_document import FileDocumentInput, file_document
from app.tools.mark_task_complete import MarkTaskCompleteInput, mark_task_complete
from app.tools.parse_document import ExtractionEngine, ParseDocumentInput, parse_document
from app.tools.send_email import SendEmailInput, send_email
from app.tools.update_coi_record import UpdateCoiRecordWriteInput, write_coi_record
from app.policy.file_guardrails import check_attachment
from app.storage import DocumentStorage, get_storage

FROM_ADDRESS_DEFAULT = "rowan@example.com"


@dataclass
class RunContext:
    org: OrganizationRow
    run: RunRow
    vendor: VendorRow
    constants: RunConstants


async def _load_context(run_id: UUID, organization_id: UUID) -> RunContext | None:
    async with org_scoped_tx(organization_id) as conn:
        run = await run_repo.get_run(conn, run_id)
        if run is None:
            return None
        org = await entity_repo.get_organization(conn, organization_id)
        vendor = await entity_repo.get_vendor(conn, run.vendor_id)
    return RunContext(org=org, run=run, vendor=vendor, constants=resolve_constants(org.settings))


def _tool_context(ctx: RunContext, action: Action) -> ToolContext:
    return ToolContext(
        run_id=ctx.run.id,
        organization_id=ctx.org.id,
        idempotency_key=f"{ctx.run.id}:{action.value}",
        budget=budget_snapshot(ctx.run, ctx.constants),
    )


def _frozen(ctx: RunContext) -> bool:
    """ADR 0002 global rule: "A frozen run takes no action and remains in
    its current state until resumed." This is deliberately checked with a
    non-read-only sentinel action (kill-switch enforcement is exempted for
    read-only actions like `evaluate_expiry`'s own read step, but the
    TRANSITION it may drive is not a read — the ADR's transition guards
    explicitly include "AND agent enabled" for exactly this reason). Every
    transition function in this module must check this before advancing
    state, even the ones triggered by a nominally read-only action.
    """
    decision = check_kill_switches(
        org_agent_enabled=ctx.org.agent_enabled,
        run_status=ctx.run.status,
        action=Action.send_first_outreach,  # any non-exempt action
    )
    return not decision.allow


async def _guard(ctx: RunContext, action: Action, *, additional_cost_cents: int = 0) -> PolicyDecision:
    return check_action(
        state=ctx.run.state,
        action=action,
        org_agent_enabled=ctx.org.agent_enabled,
        run_status=ctx.run.status,
        budget=budget_snapshot(ctx.run, ctx.constants),
        additional_cost_cents=additional_cost_cents,
    )


async def _record_guardrail_trip(ctx: RunContext, decision: PolicyDecision, action: Action) -> None:
    async with org_scoped_tx(ctx.org.id) as conn:
        await write_event(
            conn,
            organization_id=ctx.org.id,
            run_id=ctx.run.id,
            vendor_id=ctx.vendor.id,
            event_type=EventType.guardrail_trip,
            name=f"orchestration.{action.value}.denied",
            severity=EventSeverity.warn,
            payload={"reason": decision.reason, "guardrail": decision.guardrail_name},
        )


async def _transition(
    ctx: RunContext,
    *,
    to_state: RunState,
    status: RunStatus | None = None,
    extra: dict[str, Any] | None = None,
    guard_name: str,
) -> RunRow | None:
    """Atomically CAS the run to `to_state` and write the state_transition
    event in the SAME transaction — a crash here either commits both or
    neither (see run_repo.update_run_state's docstring)."""
    async with org_scoped_tx(ctx.org.id) as conn:
        updated = await run_repo.update_run_state(
            conn, ctx.run.id, from_state=ctx.run.state, to_state=to_state, status=status, extra=extra
        )
        if updated is None:
            return None  # already transitioned elsewhere (replay no-op)
        await write_event(
            conn,
            organization_id=ctx.org.id,
            run_id=ctx.run.id,
            vendor_id=ctx.vendor.id,
            event_type=EventType.state_transition,
            name=f"run.{ctx.run.state.value}_to_{to_state.value}",
            from_state=ctx.run.state,
            to_state=to_state,
            payload={"guard": guard_name},
        )
    return updated


async def _errored(ctx: RunContext, *, reason: str) -> RunRow | None:
    async with org_scoped_tx(ctx.org.id) as conn:
        updated = await run_repo.update_run_state(
            conn, ctx.run.id, from_state=ctx.run.state, to_state=RunState.errored
        )
        if updated is None:
            return None
        await write_event(
            conn,
            organization_id=ctx.org.id,
            run_id=ctx.run.id,
            vendor_id=ctx.vendor.id,
            event_type=EventType.error,
            name="run.errored",
            severity=EventSeverity.error,
            from_state=ctx.run.state,
            to_state=RunState.errored,
            payload={"reason": reason},
        )
    return updated


# --------------------------------------------------------------------------
# monitoring -> renewal_due_soon  [scheduler]
# --------------------------------------------------------------------------


async def evaluate_expiry(organization_id: UUID, run_id: UUID, *, now: date | None = None) -> RunRow | None:
    now = now or date.today()
    ctx = await _load_context(run_id, organization_id)
    if ctx is None or ctx.run.state != RunState.monitoring:
        return None

    decision = await _guard(ctx, Action.evaluate_expiry)
    if not decision.allow:
        return None  # not allowlisted for this state (shouldn't happen; defense-in-depth)

    if _frozen(ctx):
        # The read itself is allowed (evaluate_expiry is read-only), but the
        # TRANSITION it would drive is not — ADR 0002's guard explicitly
        # requires "AND agent enabled", and the global "frozen run stays put"
        # rule applies to every transition, not just outbound tool calls.
        return None

    if ctx.run.due_date is None:
        return None
    if ctx.vendor.status.value != "active":
        return None
    if now < ctx.run.due_date - timedelta(days=ctx.constants.renewal_lead_days):
        return None

    return await _transition(ctx, to_state=RunState.renewal_due_soon, guard_name="due_date_within_lead_window")


# --------------------------------------------------------------------------
# renewal_due_soon -> first_outreach_sent -> awaiting_vendor_response
#   or -> escalated_to_pm (no contact email / budget exhausted)  [scheduler]
# --------------------------------------------------------------------------


async def send_first_outreach(organization_id: UUID, run_id: UUID, *, now: datetime | None = None) -> RunRow | None:
    now = now or datetime.now(timezone.utc)
    ctx = await _load_context(run_id, organization_id)
    if ctx is None or ctx.run.state != RunState.renewal_due_soon:
        return None
    if _frozen(ctx):
        return None

    if not ctx.vendor.primary_email:
        return await _escalate(
            ctx,
            reason_code="no_contact_email",
            severity="error",
            summary=f"{ctx.vendor.name} has no contact email on file — Rowan cannot request a COI renewal.",
            details={},
        )

    decision = await _guard(ctx, Action.send_first_outreach)
    if not decision.allow:
        if decision.guardrail_name in ("outreach_budget_exhausted", "cost_budget_exhausted"):
            return await _escalate(
                ctx,
                reason_code="budget_exhausted",
                severity="error",
                summary=f"Outreach budget exhausted before reaching {ctx.vendor.name}.",
                details={"guardrail": decision.guardrail_name},
            )
        await _record_guardrail_trip(ctx, decision, Action.send_first_outreach)
        return None

    send_result = await send_email(
        _tool_context(ctx, Action.send_first_outreach),
        SendEmailInput(
            to_email=ctx.vendor.primary_email,
            from_email=FROM_ADDRESS_DEFAULT,
            template_id="first_outreach",
            template_vars={"vendor_name": ctx.vendor.name, "org_name": ctx.org.name},
            reply_token=ctx.run.reply_token,
            vendor_id=ctx.vendor.id,
            sequence=ctx.run.outreach_email_count,
        ),
    )
    if send_result.status != "ok":
        # Transient provider failure: leave the run in renewal_due_soon: the
        # next scheduler tick retries (send_email is idempotent, so this is
        # safe even if the failure was actually a false negative).
        return None

    # Cascade: first_outreach_sent is a transient bookkeeping state (ADR
    # 0002) — record it, then immediately evaluate the next guard rather
    # than waiting for a separate trigger.
    booked = await _transition(ctx, to_state=RunState.first_outreach_sent, guard_name="outreach_sent")
    if booked is None:
        return None
    ctx.run = booked

    next_action_at = now + timedelta(days=ctx.constants.followup_interval_days)
    return await _transition(
        ctx,
        to_state=RunState.awaiting_vendor_response,
        extra={"next_action_at": next_action_at},
        guard_name="send_email_returned_provider_id",
    )


async def _escalate(
    ctx: RunContext, *, reason_code: str, severity: str, summary: str, details: dict[str, Any]
) -> RunRow | None:
    async with org_scoped_tx(ctx.org.id) as conn:
        await escalate_to_pm(
            conn,
            _tool_context(ctx, Action.escalate_to_pm),
            EscalateToPmInput(
                vendor_id=ctx.vendor.id,
                kind="escalated_to_pm",
                reason_code=reason_code,
                severity=severity,
                summary=summary,
                details=details,
                run_state=ctx.run.state.value,
                vendor_name=ctx.vendor.name,
                from_email=FROM_ADDRESS_DEFAULT,
            ),
        )
    return await _transition(ctx, to_state=RunState.escalated_to_pm, guard_name=reason_code)


# --------------------------------------------------------------------------
# awaiting_vendor_response: follow-up self-loop / deadline escalation
#   (CLAUDE.md's canonical example — allowlist is EXACTLY wait /
#   follow_up_within_budget / escalate_to_pm)  [scheduler]
# --------------------------------------------------------------------------


async def check_followup_or_deadline(
    organization_id: UUID, run_id: UUID, *, now: datetime | None = None
) -> RunRow | None:
    now = now or datetime.now(timezone.utc)
    ctx = await _load_context(run_id, organization_id)
    if ctx is None or ctx.run.state != RunState.awaiting_vendor_response:
        return None
    if _frozen(ctx):
        return None

    due_date = ctx.run.due_date or date.today()
    deadline = due_date + timedelta(days=ctx.constants.response_deadline_days)
    deadline_passed = now.date() >= deadline

    max_outreach_reached = ctx.run.outreach_email_count >= ctx.constants.max_outreach

    if deadline_passed or max_outreach_reached:
        reason = "no_response"
        return await _escalate(
            ctx,
            reason_code=reason,
            severity="warn",
            summary=f"{ctx.vendor.name} has not responded to Rowan's outreach.",
            details={
                "outreach_email_count": ctx.run.outreach_email_count,
                "deadline_passed": deadline_passed,
            },
        )

    if ctx.run.next_action_at is None or now < ctx.run.next_action_at:
        return None  # not time yet

    decision = await _guard(ctx, Action.follow_up_within_budget)
    if not decision.allow:
        if decision.guardrail_name in ("outreach_budget_exhausted", "cost_budget_exhausted"):
            return await _escalate(
                ctx,
                reason_code="no_response",
                severity="warn",
                summary=f"Outreach budget exhausted while waiting on {ctx.vendor.name}.",
                details={"guardrail": decision.guardrail_name},
            )
        await _record_guardrail_trip(ctx, decision, Action.follow_up_within_budget)
        return None

    send_result = await send_email(
        _tool_context(ctx, Action.follow_up_within_budget),
        SendEmailInput(
            to_email=ctx.vendor.primary_email,
            from_email=FROM_ADDRESS_DEFAULT,
            template_id="follow_up",
            template_vars={"vendor_name": ctx.vendor.name},
            reply_token=ctx.run.reply_token,
            vendor_id=ctx.vendor.id,
            sequence=ctx.run.outreach_email_count,
        ),
    )
    if send_result.status != "ok":
        return None  # transient failure; next tick retries (idempotent)

    next_action_at = now + timedelta(days=ctx.constants.followup_interval_days)
    # Self-loop transition: CAS from awaiting_vendor_response to itself,
    # bumping next_action_at. Still goes through the same atomic
    # from_state==to_state CAS + event write as every other transition.
    return await _transition(
        ctx,
        to_state=RunState.awaiting_vendor_response,
        extra={"next_action_at": next_action_at},
        guard_name="followup_within_budget",
    )


# --------------------------------------------------------------------------
# awaiting_vendor_response -> document_received -> parsing  [webhook]
# --------------------------------------------------------------------------


async def handle_inbound_document(
    organization_id: UUID,
    run_id: UUID,
    *,
    filename: str,
    data: bytes,
    content_type: str,
    storage: DocumentStorage | None = None,
) -> RunRow | None:
    """Inbound-email webhook entry point (after the webhook layer has
    already resolved reply_token -> run -> organization_id and verified the
    provider signature — see app/webhooks/resend_inbound.py). `data` is the
    raw attachment bytes; UNTRUSTED input per CLAUDE.md, validated here
    before anything is stored or reaches parsing.
    """
    storage = storage or get_storage()
    ctx = await _load_context(run_id, organization_id)
    if ctx is None or ctx.run.state != RunState.awaiting_vendor_response:
        return None

    # # ASSUMPTION: while frozen (paused/org-disabled/global kill), an
    # inbound attachment is NOT stored or processed — it is simply dropped
    # on this delivery. This matches ADR 0002's general "frozen run takes no
    # action" rule, but is a real tradeoff: if the email provider does not
    # retry inbound webhook delivery, the vendor's document could be lost
    # until they resend. A v2 improvement would persist the raw attachment
    # unconditionally (for later reconciliation) even while frozen, without
    # advancing the state machine. Flagged for architect/product input.
    if _frozen(ctx):
        return None

    guardrail = check_attachment(filename=filename, data=data)
    if not guardrail.ok:
        async with org_scoped_tx(ctx.org.id) as conn:
            await write_event(
                conn,
                organization_id=ctx.org.id,
                run_id=ctx.run.id,
                vendor_id=ctx.vendor.id,
                event_type=EventType.guardrail_trip,
                name="inbound_attachment.rejected",
                severity=EventSeverity.warn,
                payload={"reason": guardrail.reason, "filename": filename},
            )
        return None  # stays in awaiting_vendor_response; vendor may resend

    document_id = uuid7()
    # security-reviewer finding (2026-07-18, blocking): the storage key must
    # NEVER be built from the raw, UNTRUSTED inbound filename (path
    # traversal) — derive it solely from document_id + the guardrail-
    # detected type. The original filename is preserved as metadata only
    # (`coi_documents.original_filename`), never as part of a filesystem
    # path.
    storage_path = f"{ctx.vendor.id}/{document_id}.{guardrail.detected_type}"
    await storage.write(storage_path=storage_path, data=data)

    async with org_scoped_tx(ctx.org.id) as conn:
        version = await entity_repo.next_document_version(conn, ctx.vendor.id)
        doc = await entity_repo.insert_coi_document(
            conn,
            id=document_id,
            organization_id=ctx.org.id,
            vendor_id=ctx.vendor.id,
            run_id=ctx.run.id,
            storage_path=storage_path,
            original_filename=filename,
            content_type=content_type,
            byte_size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            source="email_inbound",
            version_number=version,
        )
        updated = await run_repo.update_run_state(
            conn,
            ctx.run.id,
            from_state=RunState.awaiting_vendor_response,
            to_state=RunState.document_received,
            extra={"coi_document_id": doc.id},
        )
        if updated is None:
            return None  # replay: run already left awaiting_vendor_response
        await write_event(
            conn,
            organization_id=ctx.org.id,
            run_id=ctx.run.id,
            vendor_id=ctx.vendor.id,
            event_type=EventType.state_transition,
            name="run.awaiting_vendor_response_to_document_received",
            from_state=RunState.awaiting_vendor_response,
            to_state=RunState.document_received,
            payload={"guard": "valid_attachment_inbound", "coi_document_id": str(doc.id)},
        )
    ctx.run = updated

    return await advance_from_document_received(organization_id, run_id)


async def advance_from_document_received(organization_id: UUID, run_id: UUID) -> RunRow | None:
    """document_received -> parsing (or -> needs_human_review if
    unclassifiable). Split out from `handle_inbound_document` so a run that
    crashes after being stored but before this cascade runs can be resumed
    by a scheduler sweep (see app/orchestration/scheduler.py), not just by
    a fresh webhook delivery.

    Per ADR 0002's 2026-07-18 amendment ("No new classify_document tool;
    classification folded into parsing"): document_received -> parsing is
    unconditional once storage/file-guardrail checks pass (no separate
    classify gate here); the actual "is this a COI" judgment now happens as
    the first LLM sub-pass inside `parse_document` itself, alongside
    extraction, sharing one per-document LLM budget.

    # ASSUMPTION (ratified by the architect as an acceptable interim state,
    not a design deviation): until agent-engineer wires that classify
    sub-pass, this codebase ships the deterministic stopgap described in the
    amendment — any attachment that already passed the pre-LLM file-type/size
    guardrails (app/policy/file_guardrails.py) is treated as a COI candidate
    and sent to parsing; non-COI documents are caught downstream by
    parse_document's low-confidence routing to needs_human_review, never
    guessed.
    """
    ctx = await _load_context(run_id, organization_id)
    if ctx is None or ctx.run.state != RunState.document_received:
        return None
    if _frozen(ctx):
        return None

    # Reset the per-document LLM budget when a NEW document enters parsing
    # (see app/tools/base.py's ASSUMPTION docstring for why this lives here).
    # `cost_cents_spent` is deliberately NOT reset here: BUDGET_COST_CAP_CENTS
    # is a per-RUN-CYCLE cap (CLAUDE.md: "max configurable $ per run"), not
    # per-document — resetting it per document would let repeated
    # PM-requested revisions blow past the configured cap in unbounded
    # increments across multiple documents in the same run. (Bug caught by
    # architect review; regression test:
    # tests/test_orchestration_document_pipeline.py::
    # test_cost_cents_spent_accumulates_across_documents_in_same_run_cycle)
    return await _transition(
        ctx,
        to_state=RunState.parsing,
        extra={"llm_call_count": 0},
        guard_name="stored_and_classified_as_coi",
    )


# --------------------------------------------------------------------------
# parsing -> validating | needs_human_review  [tool: parse_document]
# --------------------------------------------------------------------------


async def run_parsing(
    organization_id: UUID,
    run_id: UUID,
    *,
    engine: ExtractionEngine | None = None,
    attempt_no: int = 0,
    storage: DocumentStorage | None = None,
) -> RunRow | None:
    ctx = await _load_context(run_id, organization_id)
    if ctx is None or ctx.run.state != RunState.parsing:
        return None
    if _frozen(ctx):
        return None
    if ctx.run.coi_document_id is None:
        return await _errored(ctx, reason="parsing_state_with_no_coi_document_id")

    decision = await _guard(ctx, Action.parse_document)
    if not decision.allow:
        if decision.guardrail_name in ("llm_budget_exhausted", "cost_budget_exhausted"):
            return await _transition(
                ctx, to_state=RunState.needs_human_review, guard_name="extraction_budget_exhausted"
            )
        await _record_guardrail_trip(ctx, decision, Action.parse_document)
        return None

    async with org_scoped_tx(ctx.org.id) as conn:
        doc = await entity_repo.get_coi_document(conn, ctx.run.coi_document_id)

    parse_result = await parse_document(
        _tool_context(ctx, Action.parse_document),
        ParseDocumentInput(
            coi_document_id=doc.id,
            storage_path=doc.storage_path,
            content_type=doc.content_type,
            prompt_id="coi_extraction_v1",
            attempt_no=attempt_no,
            confidence_threshold=ctx.constants.confidence_threshold,
        ),
        engine=engine,
        storage=storage,
    )

    if parse_result.status != "ok":
        # Extraction failed (provider error, stub not wired, etc). Counts
        # against the per-document LLM budget already (parse_document
        # increments it even on failure). Stay in `parsing`; the next
        # attempt (bumped attempt_no) is a fresh idempotency key, or the
        # budget guard above eventually routes to needs_human_review.
        return None

    # Re-read the run: parse_document already incremented llm_call_count /
    # cost_cents_spent as part of its own committed transaction.
    ctx2 = await _load_context(run_id, organization_id)
    if ctx2 is None or ctx2.run.state != RunState.parsing:
        return None
    ctx = ctx2

    overall_confidence = parse_result.data.overall_confidence
    if overall_confidence < ctx.constants.confidence_threshold:
        return await _transition(
            ctx, to_state=RunState.needs_human_review, guard_name="low_confidence_extraction"
        )

    return await _transition(ctx, to_state=RunState.validating, guard_name="schema_valid_and_confident")


# --------------------------------------------------------------------------
# validating -> filed | needs_human_review | escalated_to_pm
#   [tool: update_coi_record write mode]  (deterministic — no LLM decides)
# --------------------------------------------------------------------------


async def run_validation(organization_id: UUID, run_id: UUID) -> RunRow | None:
    ctx = await _load_context(run_id, organization_id)
    if ctx is None or ctx.run.state != RunState.validating:
        return None
    if _frozen(ctx):
        return None
    if ctx.run.coi_document_id is None:
        return await _errored(ctx, reason="validating_state_with_no_coi_document_id")

    async with org_scoped_tx(ctx.org.id) as conn:
        extraction = await entity_repo.get_current_extraction(conn, ctx.run.coi_document_id)
        if extraction is None:
            return await _errored(ctx, reason="validating_state_with_no_extraction")

        write_result = await write_coi_record(
            conn,
            _tool_context(ctx, Action.run_validation),
            UpdateCoiRecordWriteInput(
                coi_extraction_id=extraction.id, confidence_threshold=ctx.constants.confidence_threshold
            ),
        )

    if write_result.status != "ok":
        return await _errored(ctx, reason=f"update_coi_record_write_failed:{write_result.reason}")

    data = write_result.data

    # ADR 0005 (confirmed by qa-evals-engineer): BOTH "no requirements on
    # file at all" and "a required line has no backing KB row"
    # (faithfulness_ok=False) are the SAME retrieval-fallback/faithfulness
    # failure mode and both route to escalated_to_pm — never to
    # needs_human_review, and never validated against a guessed
    # requirement. This is checked before the pass/fail branch below.
    if data.no_requirements_on_file or not data.faithfulness_ok:
        return await _escalate(
            ctx,
            reason_code="no_requirements_on_file",
            severity="error",
            summary=(
                f"No verified compliance requirements on file for {ctx.vendor.name} "
                f"(or a required line is unverified) — Rowan cannot validate this COI."
            ),
            details={"validation_id": str(data.validation_id), "flags": data.flags},
        )

    high_severity_flags = [f for f in data.flags if f.get("severity") == "high"]
    if data.result == "pass" and not high_severity_flags:
        return await _transition(
            ctx,
            to_state=RunState.filed,
            extra={"coi_document_id": ctx.run.coi_document_id},
            guard_name="validation_passed_and_faithful",
        )

    return await _transition(ctx, to_state=RunState.needs_human_review, guard_name="validation_failed_or_flagged")


# --------------------------------------------------------------------------
# filed -> monitoring  (consequential — gated, ADR 0002 "filed" state)
# --------------------------------------------------------------------------


async def complete_filing(
    organization_id: UUID, run_id: UUID, *, valid_from: date, valid_to: date
) -> RunRow | None:
    ctx = await _load_context(run_id, organization_id)
    if ctx is None or ctx.run.state != RunState.filed:
        return None
    if _frozen(ctx):
        return None
    if ctx.run.coi_document_id is None:
        return await _errored(ctx, reason="filed_state_with_no_coi_document_id")

    # Read-only lookup phase, in its own short transaction — deliberately
    # NOT nested inside the write transaction below, so that on any error
    # path we can call `_errored` (which opens its own org_scoped_tx)
    # without two transactions racing for connections on the same logical
    # operation.
    async with org_scoped_tx(ctx.org.id) as conn:
        extraction = await entity_repo.get_current_extraction(conn, ctx.run.coi_document_id)
        validation = (
            await entity_repo.get_latest_validation_for_extraction(conn, extraction.id)
            if extraction
            else None
        )
        approved = (
            None
            if validation and validation.result.value == "pass" and validation.faithfulness_ok
            else await entity_repo.get_latest_approved_escalation(conn, ctx.run.id)
        )

    if validation is None:
        return await _errored(ctx, reason="filed_state_with_no_validation")

    basis = "validation_passed"
    if not (validation.result.value == "pass" and validation.faithfulness_ok):
        if approved is None:
            return await _errored(ctx, reason="filed_state_with_no_passing_validation_or_approval")
        basis = "human_approved"

    # Write phase: file_document + mark_task_complete are both pure-DB tools
    # (no external side effect), so bundling them in one transaction is
    # correct and atomic — either both commit or neither does.
    async with org_scoped_tx(ctx.org.id) as conn:
        file_result = await file_document(
            conn,
            _tool_context(ctx, Action.file_document),
            FileDocumentInput(coi_document_id=ctx.run.coi_document_id, valid_from=valid_from, valid_to=valid_to),
        )
        if file_result.status != "ok":
            file_failed_reason = file_result.reason
            complete_result = None
        else:
            complete_result = await mark_task_complete(
                conn,
                _tool_context(ctx, Action.mark_task_complete),
                MarkTaskCompleteInput(
                    coi_validation_id=validation.id,
                    completion_basis=basis,
                    renewal_lead_days=ctx.constants.renewal_lead_days,
                ),
            )

    if complete_result is None:
        return await _errored(ctx, reason=f"file_document_failed:{file_failed_reason}")

    if complete_result.status != "ok":
        # ADR 0004: precondition mismatch on mark_task_complete -> denied +
        # guardrail event + route to errored. Never a silent "you're
        # covered" claim on a basis that doesn't actually hold.
        return await _errored(ctx, reason=f"mark_task_complete_denied:{complete_result.reason}")

    await send_email(
        _tool_context(ctx, Action.notify_pm_handled),
        SendEmailInput(
            to_email=await _pm_email(ctx),
            from_email=FROM_ADDRESS_DEFAULT,
            template_id="handled_notice",
            template_vars={"vendor_name": ctx.vendor.name, "valid_to": str(valid_to)},
            vendor_id=ctx.vendor.id,
            sequence=f"filed-{ctx.run.coi_document_id}",
        ),
    )

    next_due_date = complete_result.data.next_due_date
    return await _transition(
        ctx,
        to_state=RunState.monitoring,
        extra={
            "due_date": next_due_date,
            "outreach_email_count": 0,
            "llm_call_count": 0,
            "cost_cents_spent": 0,
        },
        guard_name="filed_and_cycle_reset",
    )


async def _pm_email(ctx: RunContext) -> str:
    async with org_scoped_tx(ctx.org.id) as conn:
        email = await entity_repo.get_primary_user_email(conn, ctx.org.id)
    return email or FROM_ADDRESS_DEFAULT


# --------------------------------------------------------------------------
# needs_human_review -> filed | awaiting_vendor_response | escalated_to_pm
#   [human]
# --------------------------------------------------------------------------


async def resolve_needs_human_review(
    organization_id: UUID,
    run_id: UUID,
    *,
    decision: str,  # 'approve' | 'request_revision' | 'reject'
    escalation_id: UUID,
    resolved_by: UUID | None,
    revision_reason: str | None = None,
) -> RunRow | None:
    ctx = await _load_context(run_id, organization_id)
    if ctx is None or ctx.run.state != RunState.needs_human_review:
        return None
    if _frozen(ctx):
        return None

    async with org_scoped_tx(ctx.org.id) as conn:
        resolution = {"approve": "approved", "request_revision": "revision_requested", "reject": "rejected"}.get(
            decision
        )
        if resolution is None:
            return None
        await entity_repo.resolve_escalation(
            conn, escalation_id=escalation_id, resolution=resolution, resolved_by=resolved_by
        )
        await write_event(
            conn,
            organization_id=ctx.org.id,
            run_id=ctx.run.id,
            vendor_id=ctx.vendor.id,
            event_type=EventType.human_intervention,
            name=f"needs_human_review.{decision}",
            payload={"escalation_id": str(escalation_id), "decision": decision},
        )

    if decision == "approve":
        # Human-approval path for consequential completion (ADR 0002): the
        # actual filing + mark_task_complete(human_approved) happens via
        # complete_filing, reached by first transitioning to `filed`.
        return await _transition(ctx, to_state=RunState.filed, guard_name="pm_approved")

    if decision == "reject":
        return await _escalate(
            ctx,
            reason_code="rejected_by_pm",
            severity="warn",
            summary=f"PM rejected the COI for {ctx.vendor.name} without requesting a revision.",
            details={"escalation_id": str(escalation_id)},
        )

    if decision == "request_revision":
        # This action is a human-decision-triggered send tied to
        # needs_human_review's own allowlist ("on human decision,
        # transition"), not the awaiting_vendor_response allowlist a
        # follow-up would normally be checked against — so only the BUDGET
        # dimension applies here, not the full state allowlist (which would
        # incorrectly reject this because follow_up_within_budget isn't
        # allowlisted for needs_human_review). Kill-switch was already
        # checked via `_frozen(ctx)` above.
        budget_decision = check_budget(
            Action.follow_up_within_budget, budget_snapshot(ctx.run, ctx.constants)
        )
        if not budget_decision.allow:
            return await _escalate(
                ctx,
                reason_code="no_response",
                severity="warn",
                summary=f"Cannot request a revision from {ctx.vendor.name} — outreach budget exhausted.",
                details={"escalation_id": str(escalation_id)},
            )
        await send_email(
            _tool_context(ctx, Action.follow_up_within_budget),
            SendEmailInput(
                to_email=ctx.vendor.primary_email,
                from_email=FROM_ADDRESS_DEFAULT,
                template_id="revision_request",
                template_vars={"vendor_name": ctx.vendor.name, "revision_reason": revision_reason or ""},
                reply_token=ctx.run.reply_token,
                vendor_id=ctx.vendor.id,
                sequence=ctx.run.outreach_email_count,
            ),
        )
        next_action_at = datetime.now(timezone.utc) + timedelta(days=ctx.constants.followup_interval_days)
        return await _transition(
            ctx,
            to_state=RunState.awaiting_vendor_response,
            extra={"next_action_at": next_action_at},
            guard_name="pm_requested_revision",
        )

    return None


# --------------------------------------------------------------------------
# escalated_to_pm -> monitoring | awaiting_vendor_response  [human]
# --------------------------------------------------------------------------


async def resolve_escalated_to_pm(
    organization_id: UUID,
    run_id: UUID,
    *,
    decision: str,  # 'resolved' | 'keep_chasing'
    escalation_id: UUID,
    resolved_by: UUID | None,
) -> RunRow | None:
    ctx = await _load_context(run_id, organization_id)
    if ctx is None or ctx.run.state != RunState.escalated_to_pm:
        return None

    async with org_scoped_tx(ctx.org.id) as conn:
        resolution = {"resolved": "acknowledged", "keep_chasing": "revision_requested"}.get(decision)
        if resolution is None:
            return None
        await entity_repo.resolve_escalation(
            conn, escalation_id=escalation_id, resolution=resolution, resolved_by=resolved_by
        )
        await write_event(
            conn,
            organization_id=ctx.org.id,
            run_id=ctx.run.id,
            vendor_id=ctx.vendor.id,
            event_type=EventType.human_intervention,
            name=f"escalated_to_pm.{decision}",
            payload={"escalation_id": str(escalation_id), "decision": decision},
        )

    if decision == "resolved":
        return await _transition(
            ctx,
            to_state=RunState.monitoring,
            extra={"outreach_email_count": 0, "llm_call_count": 0, "cost_cents_spent": 0},
            guard_name="pm_resolved",
        )

    if decision == "keep_chasing":
        next_action_at = datetime.now(timezone.utc) + timedelta(days=ctx.constants.followup_interval_days)
        return await _transition(
            ctx,
            to_state=RunState.awaiting_vendor_response,
            extra={"next_action_at": next_action_at},
            guard_name="pm_keep_chasing",
        )

    return None


# --------------------------------------------------------------------------
# errored -> prior state  [human recovery]
# --------------------------------------------------------------------------


async def recover_from_errored(organization_id: UUID, run_id: UUID, *, to_state: RunState) -> RunRow | None:
    ctx = await _load_context(run_id, organization_id)
    if ctx is None or ctx.run.state != RunState.errored:
        return None

    async with org_scoped_tx(ctx.org.id) as conn:
        updated = await run_repo.update_run_state(
            conn, ctx.run.id, from_state=RunState.errored, to_state=to_state
        )
        if updated is None:
            return None
        await write_event(
            conn,
            organization_id=ctx.org.id,
            run_id=ctx.run.id,
            vendor_id=ctx.vendor.id,
            event_type=EventType.human_intervention,
            name="errored.recovered",
            from_state=RunState.errored,
            to_state=to_state,
            payload={"recovery_target": to_state.value},
        )
    return updated
