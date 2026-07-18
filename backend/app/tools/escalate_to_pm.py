"""`escalate_to_pm` (ADR 0004 #5). Two side effects:
  1. Upsert the `escalations` row — "one open escalation per (run, reason,
     state); re-entry updates rather than duplicates" (ADR 0004). There is
     no DB unique constraint to lean on here (unlike tool_invocations /
     coi_documents), so this is implemented as an explicit find-or-update
     rather than INSERT ... ON CONFLICT.
  2. Send the PM notice (`send_email`, template `escalation_notice`), gated
     by its OWN idempotency key (reason_code-scoped) so re-entry on the same
     open escalation updates the record but does not re-notify the PM every
     time. This notice is budget-exempt (ADR 0004 assumption: PM-directed
     notices don't count against MAX_OUTREACH).

# ASSUMPTION / known limitation: this function's own DB write (the
escalations upsert) participates in whatever transaction the caller passes
as `conn`, while `send_email` (called internally, see send_email.py's
crash-safety note) commits its own effects independently and immediately.
If the CALLER's outer transaction later rolls back for an unrelated reason,
the escalations row could be rolled back after the PM notice email already
went out — a rare inconsistency window, not a data-loss or double-send risk.
Mitigation: orchestration calls `escalate_to_pm` as the terminal action of a
processing cycle (nothing else follows it in the same transaction), which
keeps this window effectively closed in practice. Flagged for the
architect/security-reviewer rather than silently accepted.
"""

from __future__ import annotations

from uuid import UUID

import asyncpg
from pydantic import BaseModel

from app.ids import uuid7
from app.models.enums import EventSeverity, EventType, ToolStatus
from app.models.tool_contracts import PendingEvent, ToolContext, ToolOutput
from app.retrieval import entity_repo
from app.tools.send_email import SendEmailInput, send_email

TOOL_NAME = "escalate_to_pm"


class EscalateToPmInput(BaseModel):
    vendor_id: UUID
    kind: str  # 'needs_human_review' | 'escalated_to_pm'
    reason_code: str
    severity: str
    summary: str
    details: dict
    run_state: str
    vendor_name: str
    from_email: str


class EscalateToPmData(BaseModel):
    escalation_id: UUID
    kind: str
    status: str


async def escalate_to_pm(
    conn: asyncpg.Connection, context: ToolContext, input: EscalateToPmInput
) -> ToolOutput[EscalateToPmData]:
    details = {**input.details, "run_state": input.run_state}

    existing = await entity_repo.get_open_escalation(
        conn, context.run_id, input.reason_code, input.run_state
    )
    if existing is not None:
        escalation = await entity_repo.update_escalation_details(
            conn, existing.id, summary=input.summary, details=details
        )
        replay = True
    else:
        escalation = await entity_repo.insert_escalation(
            conn,
            id=uuid7(),
            organization_id=context.organization_id,
            run_id=context.run_id,
            vendor_id=input.vendor_id,
            kind=input.kind,
            reason_code=input.reason_code,
            severity=input.severity,
            summary=input.summary,
            details=details,
        )
        replay = False

    events = [
        PendingEvent(
            event_type=EventType.guardrail_trip if input.severity in ("warn", "error") else EventType.note,
            name=f"escalate_to_pm.{'updated' if replay else 'created'}",
            severity=EventSeverity(input.severity),
            tool_name=TOOL_NAME,
            payload={"reason_code": input.reason_code, "kind": input.kind},
        )
    ]

    pm_email = await entity_repo.get_primary_user_email(conn, context.organization_id)
    if pm_email:
        notice = await send_email(
            context,
            SendEmailInput(
                to_email=pm_email,
                from_email=input.from_email,
                template_id="escalation_notice",
                template_vars={"vendor_name": input.vendor_name, "summary": input.summary},
                vendor_id=input.vendor_id,
                sequence=input.reason_code,
            ),
        )
        events.extend(notice.events)

    return ToolOutput(
        status=ToolStatus.ok,
        idempotent_replay=replay,
        data=EscalateToPmData(escalation_id=escalation.id, kind=escalation.kind.value, status=escalation.status.value),
        events=events,
    )
