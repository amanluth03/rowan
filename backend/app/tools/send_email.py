"""`send_email` (ADR 0004 #1) — transport/persistence half (backend-engineer
scope). Template *content* is placeholder copy (app/tools/email_templates.py);
the Resend integration, `email_messages` write, idempotency key, and budget
caps are the real contract here.

CRASH-SAFETY DESIGN NOTE (important, applies to every tool with an external
side effect — this one and `parse_document`): this tool does NOT accept a
caller-supplied `asyncpg.Connection`, unlike the pure-DB tools
(`update_coi_record`, `file_document`, `mark_task_complete`,
`escalate_to_pm`'s own DB write). It manages TWO SEPARATE, independently
committed transactions:

  1. `reserve` — commits the `tool_invocations` row as `pending` BEFORE the
     Resend call happens. If the process crashes before this commits,
     nothing happened yet and a retry starts clean.
  2. the Resend HTTP call — outside any DB transaction (never hold a
     connection/transaction open across a network call to an external
     provider).
  3. `complete` — a second transaction, committed AFTER Resend responds,
     that writes `email_messages`, increments `runs` counters, and marks
     the invocation `succeeded`/`failed`.

If step 1 committed but the process crashes before step 3 commits, the next
retry (same idempotency key) sees a `pending` row. If its lease has expired
(app/tools/idempotency.py), the retry takes over and re-attempts — this can
in principle re-send an email if the ORIGINAL process crashed after Resend
accepted the send but before `complete()` ran. This is the one gap ADR 0004
doesn't fully close (Resend's send is not itself transactional with our DB)
and is a known, documented risk rather than a silent one.
# ASSUMPTION: acceptable for v1 given Resend's own dedupe/rate limits and
low outbound volume (max 3 outreach/run); revisit with a provider-side
idempotency-key header (Resend supports one) if this proves to bite in
practice — flagged for follow-up, not fixed here, to stay in scope.

If a DIFFERENT orchestration step around this call (e.g. the state
transition immediately after) crashes, that's fine and requires no special
handling: this tool's effects are already durably committed, so a replay of
the same trigger just calls this tool again, gets `idempotent_replay=True`
with zero new side effects, and orchestration proceeds from there.

RESOLVED (ADR 0002's 2026-07-18 amendment, item 1): `revision_request`
counts against `MAX_OUTREACH` — ADR 0002's explicit guard on
`needs_human_review`'s "(if outreach budget remains), else escalate" was
confirmed authoritative; ADR 0004's old assumption text (which grouped
`revision_request` with budget-exempt PM notices) was the stale one and has
been corrected there. `revision_request` is a message to the *vendor*
asking for a corrected document — vendor outreach by definition, regardless
of whether it was PM- or scheduler-initiated. `handled_notice` and
`escalation_notice` remain the budget-exempt PM notices (they never leave
the PM's inbox). The implementation below already matched this; no code
change was needed once the ADRs were reconciled.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel

from app.db import org_scoped_tx
from app.ids import uuid7
from app.models.enums import EventSeverity, EventType, ToolStatus
from app.models.tool_contracts import PendingEvent, ToolContext, ToolOutput
from app.retrieval import entity_repo, run_repo
from app.tools import email_templates, idempotency, keys
from app.tools.resend_client import SendResult
from app.tools.resend_client import send as resend_send

TOOL_NAME = "send_email"


class EmailTransport(Protocol):
    """DI seam for send_email's outbound call (qa-evals-engineer finding
    #5, 2026-07-18, low priority: no injectable transport existed, so
    tests/evals could never assert "was an email actually sent" against a
    controllable double — everything went through the real
    `resend_client.send`, which only ever simulates when unconfigured).
    Matches `app.tools.resend_client.send`'s signature exactly; defaults to
    that real implementation, so no caller needs to change to keep working.
    """

    async def __call__(
        self, *, to_email: str, from_email: str, subject: str, html_body: str, reply_to: str | None = None
    ) -> SendResult: ...

VENDOR_OUTREACH_TEMPLATES = {"first_outreach", "follow_up", "revision_request"}
PM_NOTICE_TEMPLATES = {"handled_notice", "escalation_notice"}
ALL_TEMPLATES = VENDOR_OUTREACH_TEMPLATES | PM_NOTICE_TEMPLATES


class SendEmailInput(BaseModel):
    to_email: str
    from_email: str
    template_id: str
    template_vars: dict[str, str] = {}
    reply_token: str | None = None
    vendor_id: UUID | None = None
    # int for vendor-outreach (0-indexed attempt number, increments
    # outreach_email_count on success); str for PM notices (a stable
    # discriminator, e.g. reason_code).
    sequence: int | str = 0


class SendEmailData(BaseModel):
    provider_message_id: str | None
    email_message_id: UUID
    delivery_status: str


async def send_email(
    context: ToolContext, input: SendEmailInput, *, transport: EmailTransport | None = None
) -> ToolOutput[SendEmailData]:
    transport = transport or resend_send
    if input.template_id not in ALL_TEMPLATES:
        return ToolOutput(status=ToolStatus.failed, reason=f"unknown template_id {input.template_id}")

    is_vendor_outreach = input.template_id in VENDOR_OUTREACH_TEMPLATES

    idempotency_key = keys.send_email_key(context.run_id, input.template_id, input.sequence)
    request_hash = keys.sha256(f"{input.to_email}|{input.template_id}|{input.sequence}")

    async with org_scoped_tx(context.organization_id) as conn:
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
                data=SendEmailData(**outcome.stored_response),
                events=[
                    PendingEvent(
                        event_type=EventType.tool_call,
                        name="send_email.replayed",
                        severity=EventSeverity.info,
                        tool_name=TOOL_NAME,
                        idempotency_key=idempotency_key,
                        payload={"template_id": input.template_id, "idempotent_replay": True},
                    )
                ],
            )
        if outcome.replay:
            return ToolOutput(status=ToolStatus.failed, idempotent_replay=True, reason="prior attempt failed")
        return ToolOutput(status=ToolStatus.denied, reason="invocation already in progress")

    subject, html_body = email_templates.render(input.template_id, input.template_vars)

    # --- external call, no DB transaction held open ---
    result = await transport(
        to_email=input.to_email,
        from_email=input.from_email,
        subject=subject,
        html_body=html_body,
        reply_to=f"{input.reply_token}@reply.rowan.example.com" if input.reply_token else None,
    )

    async with org_scoped_tx(context.organization_id) as conn:
        if not result.ok:
            await idempotency.complete(
                conn, outcome.invocation_id, status="failed", error={"reason": result.error}
            )
            return ToolOutput(status=ToolStatus.failed, reason=result.error)

        email_row = await entity_repo.insert_email_message(
            conn,
            id=uuid7(),
            organization_id=context.organization_id,
            run_id=context.run_id,
            vendor_id=input.vendor_id,
            direction="outbound",
            provider_message_id=result.provider_message_id,
            reply_token=input.reply_token,
            subject=subject,
            body_snapshot=html_body,
            to_email=input.to_email,
            from_email=input.from_email,
            status="sent",
        )

        if is_vendor_outreach:
            await run_repo.increment_counters(conn, context.run_id, outreach_delta=1)

        data = SendEmailData(
            provider_message_id=result.provider_message_id,
            email_message_id=email_row.id,
            delivery_status="sent",
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
                name="send_email.sent",
                severity=EventSeverity.info,
                tool_name=TOOL_NAME,
                idempotency_key=idempotency_key,
                payload={"template_id": input.template_id, "to_email": input.to_email},
            )
        ],
    )
