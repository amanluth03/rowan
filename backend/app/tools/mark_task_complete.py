"""`mark_task_complete` (ADR 0004 #6) — the most-gated tool. This is what
emits the "you're covered" claim, so its precondition is checked here in
code, not trusted from the caller, and re-verified regardless of what the
orchestration layer believes the state to be.

Hard precondition: allowed ONLY if
  (a) `coi_validations.result == 'pass' AND faithfulness_ok == true`
      (basis `validation_passed`), OR
  (b) an `escalation` for this run is resolved `approved`
      (basis `human_approved`).
Never on LLM judgment alone. A mismatch is a `denied` + `guardrail_trip`
event; the caller (orchestration runner) routes the run to `errored` on this
specific denial, per ADR 0004's stated failure mode for this tool
(distinct from ordinary budget/kill denials, which normally just block the
one action and stay in the current state).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import asyncpg
from pydantic import BaseModel

from app.models.enums import EventSeverity, EventType, ToolStatus
from app.models.tool_contracts import PendingEvent, ToolContext, ToolOutput
from app.retrieval import entity_repo
from app.tools import idempotency, keys

TOOL_NAME = "mark_task_complete"


class MarkTaskCompleteInput(BaseModel):
    coi_validation_id: UUID
    completion_basis: str  # 'validation_passed' | 'human_approved'
    renewal_lead_days: int


class MarkTaskCompleteData(BaseModel):
    run_id: UUID
    completed_cycle_at: datetime
    next_due_date: date | None


async def mark_task_complete(
    conn: asyncpg.Connection, context: ToolContext, input: MarkTaskCompleteInput
) -> ToolOutput[MarkTaskCompleteData]:
    idempotency_key = keys.mark_task_complete_key(context.run_id, input.coi_validation_id)
    request_hash = keys.sha256(f"{context.run_id}|{input.coi_validation_id}|{input.completion_basis}")

    outcome = await idempotency.reserve(
        conn,
        organization_id=context.organization_id,
        run_id=context.run_id,
        tool_name=TOOL_NAME,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if not outcome.proceed:
        if outcome.replay and outcome.stored_status == "succeeded":
            return ToolOutput(
                status=ToolStatus.ok,
                idempotent_replay=True,
                data=MarkTaskCompleteData(**outcome.stored_response),
            )
        if outcome.replay:
            return ToolOutput(status=ToolStatus.failed, idempotent_replay=True, reason="prior attempt failed")
        return ToolOutput(status=ToolStatus.denied, reason="invocation already in progress")

    validation = await entity_repo.get_validation(conn, input.coi_validation_id)
    if validation is None:
        await idempotency.complete(
            conn, outcome.invocation_id, status="failed", error={"reason": "validation_not_found"}
        )
        return ToolOutput(status=ToolStatus.failed, reason="coi_validation not found")

    precondition_met = False
    if input.completion_basis == "validation_passed":
        precondition_met = validation.result.value == "pass" and validation.faithfulness_ok
    elif input.completion_basis == "human_approved":
        approved = await entity_repo.get_latest_approved_escalation(conn, context.run_id)
        precondition_met = approved is not None

    if not precondition_met:
        await idempotency.complete(
            conn,
            outcome.invocation_id,
            status="failed",
            error={"reason": "precondition_not_met", "completion_basis": input.completion_basis},
        )
        return ToolOutput(
            status=ToolStatus.denied,
            reason=(
                f"mark_task_complete precondition not met for basis "
                f"'{input.completion_basis}' (validation={input.coi_validation_id})"
            ),
            guardrail_name="mark_task_complete_precondition_failed",
            events=[
                PendingEvent(
                    event_type=EventType.guardrail_trip,
                    name="mark_task_complete.precondition_failed",
                    severity=EventSeverity.error,
                    tool_name=TOOL_NAME,
                    idempotency_key=idempotency_key,
                    payload={"completion_basis": input.completion_basis},
                )
            ],
        )

    extraction = await entity_repo.get_extraction(conn, validation.coi_extraction_id)
    document = await entity_repo.get_coi_document(conn, extraction.coi_document_id) if extraction else None

    next_due_date: date | None = None
    if document is not None and document.valid_to is not None:
        next_due_date = document.valid_to - timedelta(days=input.renewal_lead_days)

    completed_at = datetime.now(timezone.utc)
    data = MarkTaskCompleteData(
        run_id=context.run_id, completed_cycle_at=completed_at, next_due_date=next_due_date
    )

    await idempotency.complete(
        conn, outcome.invocation_id, status="succeeded", response=data.model_dump(mode="json")
    )

    return ToolOutput(
        status=ToolStatus.ok,
        data=data,
        events=[
            PendingEvent(
                event_type=EventType.tool_call,
                name="mark_task_complete.completed",
                severity=EventSeverity.info,
                tool_name=TOOL_NAME,
                idempotency_key=idempotency_key,
                payload={"completion_basis": input.completion_basis},
            )
        ],
    )
