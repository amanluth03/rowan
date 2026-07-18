"""The orchestration runner (layer 2, ADR 0002). This IS the planner —
there is no free-roaming agent loop. Every function here corresponds to one
guarded transition (or a small cascade of tool-triggered transitions) from
the state machine spec. The LLM is invoked only inside `parse_document`
(classify + extract sub-passes, `run_parsing`) and a best-effort coverage-gap
explanation drafting call in `run_validation`
(`_summarize_validation_failure`) — never here directly; this module only
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
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import asyncpg

from app.db import org_scoped_tx
from app.ids import uuid7
from app.models.enums import EventSeverity, EventType, RunState, RunStatus
from app.models.tool_contracts import ToolContext
from app.observability.events import write_event
from app.orchestration.constants import RunConstants, resolve_constants
from app.policy.actions import Action
from app.policy.guardrails import PolicyDecision, check_action, check_budget, check_kill_switches
from app.retrieval import entity_repo, run_repo
from app.retrieval.models import EscalationRow, OrganizationRow, RunRow, VendorCoverageRequirementRow, VendorRow
from app.retrieval.requirements_retriever import RequirementsQuery, V1DeterministicRetriever
from app.tools.base import budget_snapshot
from app.models.coi_fields import ExtractedCoiFields
from app.tools.draft_explanation import DraftExplanationInput, ExplanationEngine, draft_explanation
from app.tools.escalate_to_pm import EscalateToPmInput, escalate_to_pm
from app.tools.file_document import FileDocumentInput, file_document
from app.tools.mark_task_complete import MarkTaskCompleteInput, mark_task_complete
from app.tools.parse_document import ExtractionEngine, ExtractionEngineError, ParseDocumentInput, parse_document
from app.tools.send_email import SendEmailInput, send_email
from app.tools.update_coi_record import UpdateCoiRecordWriteData, UpdateCoiRecordWriteInput, write_coi_record
from app.policy.file_guardrails import check_attachment
from app.storage import DocumentStorage, get_storage


class NoRequirementsOnFileError(Exception):
    """Raised by `set_requirements` when auto-retrieval finds nothing (ADR
    0005 fallback: "the agent NEVER guesses or proceeds on defaults"). The
    API layer (app/api/commands.py) catches this and surfaces the exact
    query that missed to the PM, per ADR 0005's fallback contract — this is
    the onboarding-time analogue of `validating -> escalated_to_pm`'s
    `no_requirements_on_file` guard; there is no run/escalation to attach it
    to yet at onboarding time, so it surfaces as a command error instead."""

    def __init__(self, message: str, *, query: RequirementsQuery) -> None:
        super().__init__(message)
        self.query = query


# # ASSUMPTION: neither ADR 0001 nor ADR 0004 specifies a reply_token
# lifetime. A `runs` row is long-lived (it cycles monitoring -> ... -> filed
# -> monitoring indefinitely for the SAME run/reply_token, per
# `complete_filing`'s cycle reset — see that function above), so the token
# must remain valid across many renewal cycles, not just one outreach
# attempt. Picking 2 years as a placeholder "effectively the vendor
# relationship's lifetime" default, pending real Dana input on rotation
# policy; CLAUDE.md's "short-lived tokens where supported" principle is
# honored elsewhere (webhook signature timestamps, internal bearer token)
# but doesn't cleanly apply to a token whose entire job is to survive
# exactly as long as the vendor relationship does. Flagged to architect.
REPLY_TOKEN_VALIDITY_DAYS = 730


def _default_extraction_engine() -> ExtractionEngine:
    # Lazy import: constructing ClaudeExtractionEngine touches settings/the
    # anthropic SDK, which tests that inject their own FakeEngine should
    # never need to pay for or configure. See app/tools/extraction_engine.py.
    from app.tools.extraction_engine import ClaudeExtractionEngine

    return ClaudeExtractionEngine()


def _default_explanation_engine() -> ExplanationEngine | None:
    """Best-effort: explanation drafting is descriptive-only (ADR 0004), so a
    misconfigured/absent Claude credential must never block escalation —
    callers treat a None engine (or any drafting failure) as "use the
    deterministic fallback summary", not as an error."""
    try:
        from app.tools.explanation_engine import ClaudeExplanationEngine

        return ClaudeExplanationEngine()
    except Exception:  # noqa: BLE001 — e.g. ExplanationEngineError: no API key configured
        return None

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


async def _persist_events(
    ctx: RunContext, events: list[Any], *, conn: asyncpg.Connection | None = None
) -> None:
    """Persists every `PendingEvent` a tool call returned (ADR 0004: "tools
    never write agent_events directly — they return these, and the caller
    ... persists them in the same transaction as the tool's own side
    effect, so an event is never recorded for a side effect that didn't
    commit").

    Finding #2 fix (qa-evals-engineer / coordinator, 2026-07-18): this
    helper did not exist before — nothing in this module ever called
    `.events` off an awaited tool result, so `agent_events` never received
    `tool_call`/`llm_call` rows at all (only the runner's OWN direct
    `write_event` calls for state_transition/guardrail_trip/error/
    human_intervention landed). Every call site below now captures and
    persists `.events`.

    Pass `conn` when the caller already holds the SAME transaction the
    tool's own write happened in (the DB-only tools: `write_coi_record`,
    `file_document`, `mark_task_complete`, `escalate_to_pm`'s own write) —
    this keeps the event atomically consistent with the effect it
    describes. Omit it for tools that manage their own connection(s)
    internally (`send_email`, `parse_document`, `draft_explanation`), which
    have already committed by the time their `ToolOutput` is returned to us
    — those events are persisted in a separate, immediately-following
    transaction (best-effort, same acknowledged small gap as those tools'
    own crash-safety docstrings already describe).
    """
    if not events:
        return

    async def _write_all(c: asyncpg.Connection) -> None:
        for e in events:
            await write_event(
                c,
                organization_id=ctx.org.id,
                run_id=ctx.run.id,
                vendor_id=ctx.vendor.id,
                event_type=e.event_type,
                name=e.name,
                severity=e.severity,
                tool_name=e.tool_name,
                idempotency_key=e.idempotency_key,
                llm_model=e.llm_model,
                prompt_hash=e.prompt_hash,
                input_tokens=e.input_tokens,
                output_tokens=e.output_tokens,
                cost_cents=e.cost_cents,
                latency_ms=e.latency_ms,
                payload=e.payload,
            )

    if conn is not None:
        await _write_all(conn)
        return
    async with org_scoped_tx(ctx.org.id) as new_conn:
        await _write_all(new_conn)


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
    await _persist_events(ctx, send_result.events)
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
        escalate_result = await escalate_to_pm(
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
        await _persist_events(ctx, escalate_result.events, conn=conn)
    return await _transition(ctx, to_state=RunState.escalated_to_pm, guard_name=reason_code)


async def _needs_human_review(
    ctx: RunContext, *, reason_code: str, severity: str, summary: str, details: dict[str, Any]
) -> RunRow | None:
    """Companion to `_escalate` (kind='escalated_to_pm') for the OTHER
    escalation kind, ADR 0002's `needs_human_review` state: "Allowlist:
    create/update escalation(kind=needs_human_review), notify, wait." Prior
    to this, `run_parsing`/`run_validation` transitioned straight to
    `needs_human_review` without ever creating the `escalations` row the
    human-review queue (CLAUDE.md key screen 4) and
    `resolve_needs_human_review` both depend on — a real gap, not a stylistic
    choice (qa-evals-engineer's golden-document fixtures all expect
    `escalate_to_pm` in `expected_tool_calls` for every needs_human_review
    trajectory; see tests/evals/fixtures/golden_manifest.py). `summary` may
    be LLM-drafted prose (ADR 0004) — it is attached here as data only and
    never influences the routing decision the caller already made before
    calling this.
    """
    async with org_scoped_tx(ctx.org.id) as conn:
        escalate_result = await escalate_to_pm(
            conn,
            _tool_context(ctx, Action.escalate_to_pm),
            EscalateToPmInput(
                vendor_id=ctx.vendor.id,
                kind="needs_human_review",
                reason_code=reason_code,
                severity=severity,
                summary=summary,
                details=details,
                run_state=ctx.run.state.value,
                vendor_name=ctx.vendor.name,
                from_email=FROM_ADDRESS_DEFAULT,
            ),
        )
        await _persist_events(ctx, escalate_result.events, conn=conn)
    return await _transition(ctx, to_state=RunState.needs_human_review, guard_name=reason_code)


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
    await _persist_events(ctx, send_result.events)
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


async def process_inbound_document_to_terminal(
    organization_id: UUID,
    run_id: UUID,
    *,
    filename: str,
    data: bytes,
    content_type: str,
    storage: DocumentStorage | None = None,
    engine: ExtractionEngine | None = None,
) -> RunRow | None:
    """Production entry point for the inbound-email webhook (qa-evals-
    engineer / coordinator finding #1, 2026-07-18, SEVERE: nothing in
    production ever drove `parsing -> validating -> filed -> monitoring` —
    a real inbound COI would stall in `parsing` forever). Stores the
    attachment via `handle_inbound_document`, then synchronously drives the
    SAME individual, independently-tested stage functions —
    `run_parsing` -> `run_validation` -> `advance_from_filed` — through to
    whatever terminal-for-this-pass state a guard lands on: `filed`
    (immediately cascaded further into `monitoring`), `needs_human_review`,
    `escalated_to_pm`, or `errored`. Each stage function already re-checks
    the run's CURRENT persisted state before doing anything (see each
    function's own docstring), so this wrapper adds no new state — it is
    purely a sequencing convenience, safe to call (or crash mid-call, or
    have a duplicate concurrent invocation race) exactly as safely as
    calling those functions individually already was.

    This is the FAST PATH, not the only path: `app/orchestration/
    scheduler.py`'s `parsing`/`validating`/`filed` sweeps are the SAFETY
    NET — if this process crashes mid-cascade (e.g. after `run_parsing`
    commits but before `run_validation` is called), the next scheduler tick
    resumes the run from wherever it actually persisted to, independent of
    this function ever running again for it.
    """
    result = await handle_inbound_document(
        organization_id, run_id, filename=filename, data=data, content_type=content_type, storage=storage
    )
    return await drive_to_terminal(organization_id, run_id, result, engine=engine, storage=storage)


async def drive_to_terminal(
    organization_id: UUID,
    run_id: UUID,
    current: RunRow | None,
    *,
    engine: ExtractionEngine | None = None,
    storage: DocumentStorage | None = None,
) -> RunRow | None:
    """Recursive cascade helper for `process_inbound_document_to_terminal`
    (and reusable by the scheduler's recovery sweeps for the same states).
    Stops as soon as a stage function returns `None` (guard not satisfied /
    already elsewhere / transient failure — never retried in a tight loop
    here; the NEXT trigger, whether a scheduler tick or another webhook
    delivery, re-evaluates) or lands on a state this function doesn't know
    how to advance further (needs_human_review, escalated_to_pm, errored,
    or `monitoring` once `advance_from_filed` completes the cycle).
    """
    if current is None:
        return None
    try:
        if current.state == RunState.document_received:
            nxt = await advance_from_document_received(organization_id, run_id)
            return await drive_to_terminal(organization_id, run_id, nxt, engine=engine, storage=storage)
        if current.state == RunState.parsing:
            nxt = await run_parsing(organization_id, run_id, engine=engine, storage=storage)
            return await drive_to_terminal(organization_id, run_id, nxt, engine=engine, storage=storage)
        if current.state == RunState.validating:
            nxt = await run_validation(organization_id, run_id)
            return await drive_to_terminal(organization_id, run_id, nxt, engine=engine, storage=storage)
        if current.state == RunState.filed:
            nxt = await advance_from_filed(organization_id, run_id)
            return await drive_to_terminal(organization_id, run_id, nxt, engine=engine, storage=storage)
    except ExtractionEngineError:
        # No engine configured (e.g. ANTHROPIC_API_KEY unset) or a
        # provider-level failure at engine CONSTRUCTION time (which raises
        # before run_parsing's own per-call error handling can catch it) —
        # treat as "cannot process right now," not a crash. The run stays
        # in whatever state it last persisted to; the next scheduler tick
        # (once configured) or webhook retry resumes it.
        return None
    return current


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
    """Two-pass per ADR 0004's 2026-07-18 amendment: a cheap `classify`
    sub-call runs first (is this actually a COI at all?); only if it clears
    threshold does the accuracy-critical `extract` sub-call run. Both are
    separate calls to the `parse_document` TOOL (each its own idempotency
    key + its own `llm_call_count` increment, per ADR 0004: "prompt_id
    distinguishes the classify sub-call from the extract sub-call, so each
    has its own idempotent replay slot") — not two calls bundled inside one
    tool invocation. `engine` defaults to the real `ClaudeExtractionEngine`
    (lazy-imported, see `_default_extraction_engine` above) so production
    callers don't have to remember to wire it; tests inject their own
    FakeEngine/test double exactly as before.
    """
    engine = engine or _default_extraction_engine()

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
            return await _needs_human_review(
                ctx,
                reason_code="extraction_budget_exhausted",
                severity="warn",
                summary=(
                    f"Rowan could not finish reading {ctx.vendor.name}'s certificate within the "
                    f"per-document processing budget. Please review the document manually."
                ),
                details={"guardrail": decision.guardrail_name},
            )
        await _record_guardrail_trip(ctx, decision, Action.parse_document)
        return None

    async with org_scoped_tx(ctx.org.id) as conn:
        doc = await entity_repo.get_coi_document(conn, ctx.run.coi_document_id)

    # --- sub-pass 1: classify -------------------------------------------
    classify_result = await parse_document(
        _tool_context(ctx, Action.parse_document),
        ParseDocumentInput(
            coi_document_id=doc.id,
            storage_path=doc.storage_path,
            content_type=doc.content_type,
            prompt_id="classify",
            attempt_no=attempt_no,
            confidence_threshold=ctx.constants.confidence_threshold,
        ),
        engine=engine,
        storage=storage,
    )
    await _persist_events(ctx, classify_result.events)
    if classify_result.status != "ok":
        # Stay in `parsing`; a later re-invocation (bumped attempt_no) is a
        # fresh idempotency key, or the budget guard above eventually routes
        # to needs_human_review once MAX_LLM_PER_DOC is exhausted.
        return None

    ctx2 = await _load_context(run_id, organization_id)
    if ctx2 is None or ctx2.run.state != RunState.parsing:
        return None
    ctx = ctx2

    classify_confidence = classify_result.data.overall_confidence
    if not classify_result.data.is_coi or classify_confidence < ctx.constants.confidence_threshold:
        return await _needs_human_review(
            ctx,
            reason_code="unclassifiable_document",
            severity="warn",
            summary=(
                f"The document received for {ctx.vendor.name} does not appear to be a "
                f"certificate of insurance"
                + (f" (looked like: {classify_result.data.document_type})" if classify_result.data.document_type else "")
                + ". Please review it manually."
            ),
            details={
                "document_type": classify_result.data.document_type,
                "classify_confidence": classify_confidence,
            },
        )

    # Re-check budget before the second sub-call: classify just consumed
    # one of the MAX_LLM_PER_DOC slots.
    decision = await _guard(ctx, Action.parse_document)
    if not decision.allow:
        if decision.guardrail_name in ("llm_budget_exhausted", "cost_budget_exhausted"):
            return await _needs_human_review(
                ctx,
                reason_code="extraction_budget_exhausted",
                severity="warn",
                summary=(
                    f"Rowan classified {ctx.vendor.name}'s document as a certificate of insurance "
                    f"but ran out of processing budget before extracting coverage details. Please "
                    f"review the document manually."
                ),
                details={"guardrail": decision.guardrail_name},
            )
        await _record_guardrail_trip(ctx, decision, Action.parse_document)
        return None

    # --- sub-pass 2: extract ---------------------------------------------
    parse_result = await parse_document(
        _tool_context(ctx, Action.parse_document),
        ParseDocumentInput(
            coi_document_id=doc.id,
            storage_path=doc.storage_path,
            content_type=doc.content_type,
            prompt_id="extract",
            attempt_no=attempt_no,
            confidence_threshold=ctx.constants.confidence_threshold,
        ),
        engine=engine,
        storage=storage,
    )
    await _persist_events(ctx, parse_result.events)

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
        return await _needs_human_review(
            ctx,
            reason_code="low_confidence_extraction",
            severity="warn",
            summary=(
                f"Rowan read {ctx.vendor.name}'s certificate but was not confident enough in the "
                f"extracted coverage details (confidence {overall_confidence:.2f}) to validate it "
                f"automatically. Please review the document manually."
            ),
            details={"overall_confidence": overall_confidence},
        )

    return await _transition(ctx, to_state=RunState.validating, guard_name="schema_valid_and_confident")


# --------------------------------------------------------------------------
# validating -> filed | needs_human_review | escalated_to_pm
#   [tool: update_coi_record write mode]  (deterministic — no LLM decides)
# --------------------------------------------------------------------------


async def run_validation(organization_id: UUID, run_id: UUID, *, now: date | None = None) -> RunRow | None:
    # qa-evals-engineer finding #4 (2026-07-18): thread an explicit `now`
    # through to write_coi_record's `as_of`, the same way evaluate_expiry/
    # send_first_outreach/check_followup_or_deadline already accept `now` —
    # this was previously left to silently default to wall-clock
    # date.today() inside validation_logic.py.
    now = now or date.today()
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
                coi_extraction_id=extraction.id,
                confidence_threshold=ctx.constants.confidence_threshold,
                as_of=now,
            ),
        )
        await _persist_events(ctx, write_result.events, conn=conn)

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

    summary = await _summarize_validation_failure(ctx, data=data)
    return await _needs_human_review(
        ctx,
        reason_code="validation_failed",
        severity="warn",
        summary=summary,
        details={"validation_id": str(data.validation_id), "flags": data.flags, "line_results": data.line_results},
    )


async def _summarize_validation_failure(ctx: RunContext, *, data: UpdateCoiRecordWriteData) -> str:
    """Best-effort coverage-gap explanation (CLAUDE.md canonical pipeline
    step; ADR 0002/0004: "descriptive only... never gates the escalation").
    Attempts a `draft_explanation` LLM call gated by the SAME per-document
    LLM budget parse_document shares (Action.draft_explanation is in
    app/policy/guardrails.py's LLM_ACTIONS) — on ANY failure (budget denied,
    no engine configured, provider error), falls back to a deterministic,
    still-informative summary built straight from the flags. Routing to
    needs_human_review already happened in the caller before this runs; this
    function can only ever change the TEXT attached to that escalation.
    """
    deterministic_fallback = (
        f"{ctx.vendor.name}'s certificate did not pass automated coverage validation "
        f"(faithfulness_ok={data.faithfulness_ok}). Flags: "
        f"{', '.join(f.get('code', '?') for f in data.flags) or 'none'}. Please review the "
        f"parsed values against the requirements."
    )

    decision = await _guard(ctx, Action.draft_explanation)
    if not decision.allow:
        return deterministic_fallback

    engine = _default_explanation_engine()
    if engine is None:
        return deterministic_fallback

    result = await draft_explanation(
        _tool_context(ctx, Action.draft_explanation),
        DraftExplanationInput(
            coi_validation_id=data.validation_id,
            vendor_name=ctx.vendor.name,
            result=data.result,
            line_results=data.line_results,
            flags=data.flags,
            faithfulness_ok=data.faithfulness_ok,
        ),
        engine=engine,
    )
    await _persist_events(ctx, result.events)
    if result.status != "ok" or result.data is None:
        return deterministic_fallback
    return result.data.explanation_text


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
        await _persist_events(ctx, file_result.events, conn=conn)
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
            await _persist_events(ctx, complete_result.events, conn=conn)

    if complete_result is None:
        return await _errored(ctx, reason=f"file_document_failed:{file_failed_reason}")

    if complete_result.status != "ok":
        # ADR 0004: precondition mismatch on mark_task_complete -> denied +
        # guardrail event + route to errored. Never a silent "you're
        # covered" claim on a basis that doesn't actually hold.
        return await _errored(ctx, reason=f"mark_task_complete_denied:{complete_result.reason}")

    notice_result = await send_email(
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
    await _persist_events(ctx, notice_result.events)

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


async def advance_from_filed(organization_id: UUID, run_id: UUID) -> RunRow | None:
    """filed -> monitoring, deriving `valid_from`/`valid_to` from the
    current extraction automatically. `complete_filing` itself stays a pure
    function taking explicit dates (useful for tests and any future
    PM-override path) — this is the production caller nothing wired up
    before now (qa-evals-engineer / coordinator finding #3, 2026-07-18).
    """
    ctx = await _load_context(run_id, organization_id)
    if ctx is None or ctx.run.state != RunState.filed:
        return None
    if _frozen(ctx):
        return None
    if ctx.run.coi_document_id is None:
        return await _errored(ctx, reason="filed_state_with_no_coi_document_id")

    async with org_scoped_tx(ctx.org.id) as conn:
        extraction = await entity_repo.get_current_extraction(conn, ctx.run.coi_document_id)

    if extraction is None:
        return await _errored(ctx, reason="filed_state_with_no_extraction_to_derive_dates_from")

    fields = ExtractedCoiFields.model_validate(extraction.extracted)

    valid_to = fields.policy_expiration_date
    if valid_to is None:
        # Defense-in-depth, not the expected path: validating -> filed's
        # guard already requires a passing validation, and
        # evaluate_validation fails any extraction missing
        # policy_expiration_date (validation_logic.py's
        # missing_expiration_date check) — so this should be unreachable in
        # practice. Fail safe rather than guess a coverage end date.
        return await _errored(ctx, reason="filed_state_with_no_policy_expiration_date")

    valid_from = fields.policy_effective_date
    if valid_from is None:
        # # ASSUMPTION: evaluate_validation does not currently REQUIRE
        # policy_effective_date to be present (it only checks "not yet
        # effective" when the field IS present — see
        # app/tools/validation_logic.py) — flagged as a validation_logic
        # gap worth tightening, not fixed here to avoid changing pass/fail
        # semantics qa-evals-engineer's golden fixtures already assert
        # against. Fallback: the date Rowan actually processed the
        # extraction, which is a defensible "coverage presumed to start no
        # later than" default and, unlike guessing a policy date, is itself
        # a real, non-fabricated timestamp already on the row.
        valid_from = extraction.created_at.date()

    return await complete_filing(organization_id, run_id, valid_from=valid_from, valid_to=valid_to)


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
        revision_result = await send_email(
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
        await _persist_events(ctx, revision_result.events)
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


# --------------------------------------------------------------------------
# Interface -> Orchestration commands (ADR 0003): AddVendor, SetRequirements,
# StartRun, PauseRun, ResumeRun, ApproveReview, RejectReview, RequestRevision,
# ResolveEscalation. These are the entry points app/api/commands.py calls —
# the Interface layer never touches app/retrieval or app/tools directly
# (ADR 0003 hard rule #3).
# --------------------------------------------------------------------------


async def add_vendor(
    organization_id: UUID,
    *,
    name: str,
    primary_email: str | None,
    vendor_role: str,
    primary_property_id: UUID | None,
    notes: str | None,
    due_date: date | None,
) -> tuple[VendorRow, RunRow]:
    """AddVendor (ADR 0003). Creates the vendor AND the `runs` row for its
    initial renewal cycle in one atomic transaction — a vendor is only ever
    meaningful with an active run behind it (partial-unique
    `runs(vendor_id) where status='active'`, ADR 0001), so onboarding creates
    both together rather than leaving a vendor momentarily run-less.

    `due_date` is the current COI's known expiry, if any (PM-supplied at
    onboarding; CLAUDE.md non-goals exclude OCR/bulk-import auto-detection of
    this in v1). If omitted, the run starts in `monitoring` with `due_date =
    NULL` — `evaluate_expiry`'s guard already treats that as "nothing to do
    yet" (see that function above), so this is safe; the PM can bring the
    cycle forward explicitly later via `StartRun`.

    Security-reviewer's binding condition (flagged in two prior reviews):
    `reply_token` MUST be a CSPRNG-generated value, not a predictable/short
    token — `secrets.token_urlsafe(32)` (256 bits of entropy) below resolves
    this. `reply_token_expires_at` is a real, non-null timestamp (see
    REPLY_TOKEN_VALIDITY_DAYS's ASSUMPTION above for the lifetime choice).
    """
    async with org_scoped_tx(organization_id) as conn:
        org = await entity_repo.get_organization(conn, organization_id)
        if org is None:
            raise ValueError("organization not found")
        if primary_property_id is not None:
            prop = await entity_repo.get_property(conn, primary_property_id)
            if prop is None:
                raise ValueError(f"property {primary_property_id} not found")

        vendor = await entity_repo.insert_vendor(
            conn,
            id=uuid7(),
            organization_id=organization_id,
            name=name,
            primary_email=primary_email,
            vendor_role=vendor_role,
            primary_property_id=primary_property_id,
            notes=notes,
        )

        constants = resolve_constants(org.settings)
        reply_token = secrets.token_urlsafe(32)
        reply_token_expires_at = datetime.now(timezone.utc) + timedelta(days=REPLY_TOKEN_VALIDITY_DAYS)

        run = await run_repo.create_run(
            conn,
            organization_id=organization_id,
            vendor_id=vendor.id,
            trigger="renewal_due" if due_date is not None else "manual",
            due_date=due_date,
            budget_cost_cap_cents=constants.budget_cost_cap_cents,
            reply_token=reply_token,
            reply_token_expires_at=reply_token_expires_at,
        )

        await write_event(
            conn,
            organization_id=organization_id,
            run_id=run.id,
            vendor_id=vendor.id,
            event_type=EventType.note,
            name="vendor.added",
            payload={"vendor_name": vendor.name, "due_date": due_date.isoformat() if due_date else None},
        )

    return vendor, run


async def set_requirements(
    organization_id: UUID,
    vendor_id: UUID,
    *,
    lines: list[dict[str, Any]] | None = None,
) -> list[VendorCoverageRequirementRow]:
    """SetRequirements (ADR 0003). Two modes:

    - `lines=None` (auto): resolves the vendor's jurisdiction/property
      context (via `vendors.primary_property_id`, the locked "one set per
      vendor, resolved from primary property" rule, ADR 0005) and retrieves
      the applicable set from `compliance_requirements` via
      `V1DeterministicRetriever`. If retrieval returns `found=False`, raises
      `NoRequirementsOnFileError` — per ADR 0005's fallback, this command
      NEVER materializes guessed/default requirements.
    - `lines=[...]`: PM-supplied lines (explicit values per coverage_type,
      each optionally citing an existing, active `compliance_requirements`
      row by id — a PM can also submit an uncited override, which
      `validation_logic.py` already knows to flag as `unverified_requirement`
      per ADR 0001's `# ASSUMPTION` on `source_compliance_requirement_id`
      being nullable).

    Either way, calling this command IS the PM confirmation act — every
    materialized line gets `confirmed_by_pm=True` (CLAUDE.md: onboarding
    screen imports/pre-fills, but a human still confirms).
    """
    async with org_scoped_tx(organization_id) as conn:
        vendor = await entity_repo.get_vendor(conn, vendor_id)
        if vendor is None:
            raise ValueError(f"vendor {vendor_id} not found")

        resolved_lines: list[dict[str, Any]]

        if lines is not None:
            resolved_lines = []
            for line in lines:
                source_id = line.get("source_compliance_requirement_id")
                if source_id is not None:
                    kb = await entity_repo.get_compliance_requirement(conn, source_id)
                    if kb is None or not kb.active:
                        raise ValueError(
                            f"compliance_requirement {source_id} not found or inactive"
                        )
                resolved_lines.append(line)
        else:
            if vendor.primary_property_id is None:
                raise NoRequirementsOnFileError(
                    f"Vendor {vendor.name} has no primary_property_id — cannot resolve a "
                    f"jurisdiction/property context to retrieve requirements for.",
                    query=RequirementsQuery(
                        organization_id=organization_id,
                        jurisdiction_state="",
                        jurisdiction_city=None,
                        jurisdiction_hoa=None,
                        property_type=None,
                        vendor_role=vendor.vendor_role,
                    ),
                )
            prop = await entity_repo.get_property(conn, vendor.primary_property_id)
            if prop is None:
                raise ValueError(f"property {vendor.primary_property_id} not found")

            query = RequirementsQuery(
                organization_id=organization_id,
                jurisdiction_state=prop.state,
                jurisdiction_city=prop.city,
                jurisdiction_hoa=prop.hoa_name,
                property_type=prop.property_type,
                vendor_role=vendor.vendor_role,
            )
            retriever = V1DeterministicRetriever(conn)
            result = await retriever.retrieve(query)
            if not result.found:
                raise NoRequirementsOnFileError(
                    f"No verified compliance requirements on file for "
                    f"{prop.state}/{prop.city or 'any city'}/{vendor.vendor_role.value}.",
                    query=query,
                )
            resolved_lines = [
                {
                    "coverage_type": r.coverage_type.value,
                    "min_each_occurrence": r.min_each_occurrence,
                    "min_aggregate": r.min_aggregate,
                    "requires_additional_insured": r.requires_additional_insured,
                    "requires_waiver_of_subrogation": r.requires_waiver_of_subrogation,
                    "requires_primary_noncontributory": r.requires_primary_noncontributory,
                    "source_compliance_requirement_id": r.id,
                }
                for r in result.requirements
            ]

        materialized: list[VendorCoverageRequirementRow] = []
        for line in resolved_lines:
            vcr = await entity_repo.upsert_vendor_coverage_requirement(
                conn,
                id=uuid7(),
                organization_id=organization_id,
                vendor_id=vendor_id,
                coverage_type=line["coverage_type"],
                min_each_occurrence=line.get("min_each_occurrence"),
                min_aggregate=line.get("min_aggregate"),
                requires_additional_insured=bool(line.get("requires_additional_insured", False)),
                requires_waiver_of_subrogation=bool(line.get("requires_waiver_of_subrogation", False)),
                requires_primary_noncontributory=bool(line.get("requires_primary_noncontributory", False)),
                source_compliance_requirement_id=line.get("source_compliance_requirement_id"),
                confirmed_by_pm=True,
            )
            materialized.append(vcr)

        await write_event(
            conn,
            organization_id=organization_id,
            run_id=None,
            vendor_id=vendor_id,
            event_type=EventType.note,
            name="vendor.requirements_set",
            payload={
                "coverage_types": [line["coverage_type"] for line in resolved_lines],
                "auto_retrieved": lines is None,
            },
        )

    return materialized


async def start_run_now(organization_id: UUID, run_id: UUID, *, now: datetime | None = None) -> RunRow | None:
    """StartRun (ADR 0003) — a "kill-switch-adjacent" run-lifecycle control,
    the PM-initiated counterpart to the scheduler's date-driven
    `evaluate_expiry`. ADR 0002 only specifies a `scheduler` trigger for
    `monitoring -> renewal_due_soon` (guard: due_date - lead reached); this
    adds a `human` trigger for the SAME edge that bypasses the date guard
    entirely (a PM explicitly asking Rowan to request this vendor's COI
    right now, e.g. at onboarding, or because they know something the
    schedule doesn't). No new state, no new edge shape — same transition,
    same guarded cascade into `send_first_outreach` — only a new trigger
    kind for an edge ADR 0002 didn't enumerate a human variant for.
    # ASSUMPTION: flagged to architect as a state-machine-adjacent addition
    worth a look, not a redesign — see PR description.
    """
    now = now or datetime.now(timezone.utc)
    ctx = await _load_context(run_id, organization_id)
    if ctx is None:
        return None
    if ctx.run.state not in (RunState.monitoring, RunState.renewal_due_soon):
        return None  # already in flight (or terminal) — manual start only applies pre-outreach
    if _frozen(ctx):
        return None

    if ctx.run.state == RunState.monitoring:
        transitioned = await _transition(ctx, to_state=RunState.renewal_due_soon, guard_name="manual_start")
        if transitioned is None:
            return None
        ctx.run = transitioned

    return await send_first_outreach(organization_id, run_id, now=now)


async def pause_run(organization_id: UUID, run_id: UUID, *, paused_by: UUID | None) -> RunRow | None:
    """PauseRun (ADR 0003) — the run-level kill switch, "PM takes over" per
    CLAUDE.md. `check_kill_switches` (app/policy/guardrails.py) already
    treats `runs.status == 'paused'` as freezing every outbound action for
    this run; this command is simply the write path for that flag, plus the
    trace event so a pause is visible in the run's timeline, not a silent
    state change.
    """
    ctx = await _load_context(run_id, organization_id)
    if ctx is None or ctx.run.status != RunStatus.active:
        return None  # no-op if already paused/completed/errored — idempotent
    async with org_scoped_tx(organization_id) as conn:
        updated = await run_repo.set_run_status(conn, run_id, RunStatus.paused, paused_by=paused_by)
        await write_event(
            conn,
            organization_id=organization_id,
            run_id=run_id,
            vendor_id=ctx.vendor.id,
            event_type=EventType.human_intervention,
            name="run.paused",
            payload={"paused_by": str(paused_by) if paused_by else None},
        )
    return updated


async def resume_run(organization_id: UUID, run_id: UUID) -> RunRow | None:
    """ResumeRun (ADR 0003) — un-freezes a PM-paused run. The run resumes
    from whatever state it was frozen in; no transition happens here, the
    next scheduler tick / webhook / human action re-evaluates that state's
    guards normally now that `check_kill_switches` no longer denies it."""
    ctx = await _load_context(run_id, organization_id)
    if ctx is None or ctx.run.status != RunStatus.paused:
        return None  # no-op if not currently paused — idempotent
    async with org_scoped_tx(organization_id) as conn:
        updated = await run_repo.set_run_status(conn, run_id, RunStatus.active, paused_by=None)
        await write_event(
            conn,
            organization_id=organization_id,
            run_id=run_id,
            vendor_id=ctx.vendor.id,
            event_type=EventType.human_intervention,
            name="run.resumed",
            payload={},
        )
    return updated


async def _load_open_escalation_for_command(
    organization_id: UUID, escalation_id: UUID, *, expected_kind: str
) -> EscalationRow | None:
    """Shared guard for the four review/escalation commands below.

    security-reviewer's flagged observation (non-blocking, prior review):
    `escalations` rows are created keyed on the run_state AT CREATION TIME
    (see `entity_repo.get_open_escalation`, used only by `escalate_to_pm`'s
    own internal dedupe). Dispatch from the API must NOT repeat that mistake
    by joining against the run's CURRENT state — it looks the escalation up
    by `kind` + `status='open'` ONLY, so a review-queue item is resolvable
    exactly as long as it's actually open, independent of whatever the run
    has done since. RLS (via org_scoped_tx) already prevents cross-org
    access; this adds the kind/status/ownership checks a bare `escalation_id`
    path param can't otherwise guarantee.
    """
    async with org_scoped_tx(organization_id) as conn:
        esc = await entity_repo.get_escalation(conn, escalation_id)
    if esc is None or esc.status.value != "open" or esc.kind.value != expected_kind:
        return None
    return esc


async def approve_review(
    organization_id: UUID, escalation_id: UUID, *, resolved_by: UUID | None
) -> RunRow | None:
    """ApproveReview (ADR 0003) -> resolve_needs_human_review(decision='approve')."""
    esc = await _load_open_escalation_for_command(
        organization_id, escalation_id, expected_kind="needs_human_review"
    )
    if esc is None:
        return None
    return await resolve_needs_human_review(
        organization_id, esc.run_id, decision="approve", escalation_id=escalation_id, resolved_by=resolved_by
    )


async def reject_review(
    organization_id: UUID, escalation_id: UUID, *, resolved_by: UUID | None
) -> RunRow | None:
    """RejectReview (ADR 0003) -> resolve_needs_human_review(decision='reject')."""
    esc = await _load_open_escalation_for_command(
        organization_id, escalation_id, expected_kind="needs_human_review"
    )
    if esc is None:
        return None
    return await resolve_needs_human_review(
        organization_id, esc.run_id, decision="reject", escalation_id=escalation_id, resolved_by=resolved_by
    )


async def request_revision(
    organization_id: UUID,
    escalation_id: UUID,
    *,
    resolved_by: UUID | None,
    revision_reason: str | None = None,
) -> RunRow | None:
    """RequestRevision (ADR 0003) -> resolve_needs_human_review(decision='request_revision')."""
    esc = await _load_open_escalation_for_command(
        organization_id, escalation_id, expected_kind="needs_human_review"
    )
    if esc is None:
        return None
    return await resolve_needs_human_review(
        organization_id,
        esc.run_id,
        decision="request_revision",
        escalation_id=escalation_id,
        resolved_by=resolved_by,
        revision_reason=revision_reason,
    )


async def resolve_escalation(
    organization_id: UUID,
    escalation_id: UUID,
    *,
    decision: str,  # 'resolved' | 'keep_chasing'
    resolved_by: UUID | None,
) -> RunRow | None:
    """ResolveEscalation (ADR 0003) -> resolve_escalated_to_pm(...). This is
    the `kind='escalated_to_pm'` counterpart to Approve/Reject/RequestRevision
    (which are all `kind='needs_human_review'`) — the PM-escalations queue,
    not the document-review queue.
    """
    esc = await _load_open_escalation_for_command(
        organization_id, escalation_id, expected_kind="escalated_to_pm"
    )
    if esc is None:
        return None
    return await resolve_escalated_to_pm(
        organization_id, esc.run_id, decision=decision, escalation_id=escalation_id, resolved_by=resolved_by
    )
