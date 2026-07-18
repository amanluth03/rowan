"""`file_document` (ADR 0004 #4). Marks a coi_document `is_current`,
supersedes the prior current doc, sets `status='filed'`. Only reachable from
the `filed` run state (orchestration enforces the allowlist/guard — passing
validation OR human approval already happened before this tool is called;
see app/orchestration/runner.py's `filed` state handling).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

import asyncpg
from pydantic import BaseModel

from app.models.enums import EventSeverity, EventType, ToolStatus
from app.models.tool_contracts import PendingEvent, ToolContext, ToolOutput
from app.retrieval import entity_repo
from app.tools import idempotency, keys

TOOL_NAME = "file_document"


class FileDocumentInput(BaseModel):
    coi_document_id: UUID
    valid_from: date
    valid_to: date


class FileDocumentData(BaseModel):
    coi_document_id: UUID
    is_current: bool
    superseded_document_id: UUID | None
    filed_at: datetime


async def file_document(
    conn: asyncpg.Connection, context: ToolContext, input: FileDocumentInput
) -> ToolOutput[FileDocumentData]:
    idempotency_key = keys.file_document_key(input.coi_document_id)
    request_hash = keys.sha256(f"{input.coi_document_id}|{input.valid_from}|{input.valid_to}")

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
                status=ToolStatus.ok, idempotent_replay=True, data=FileDocumentData(**outcome.stored_response)
            )
        if outcome.replay:
            return ToolOutput(status=ToolStatus.failed, idempotent_replay=True, reason="prior attempt failed")
        return ToolOutput(status=ToolStatus.denied, reason="invocation already in progress")

    try:
        doc, superseded_id = await entity_repo.file_coi_document(
            conn,
            coi_document_id=input.coi_document_id,
            valid_from=input.valid_from,
            valid_to=input.valid_to,
        )
    except asyncpg.UniqueViolationError:
        # Partial-unique `coi_documents(vendor_id) where is_current` tripped
        # by a concurrent/duplicate filer -> treat as idempotent replay of
        # an already-filed document (ADR 0004 failure mode).
        doc = await entity_repo.get_coi_document(conn, input.coi_document_id)
        data = FileDocumentData(
            coi_document_id=doc.id,
            is_current=doc.is_current,
            superseded_document_id=doc.supersedes_document_id,
            filed_at=datetime.now(timezone.utc),
        )
        await idempotency.complete(
            conn, outcome.invocation_id, status="succeeded", response=data.model_dump(mode="json")
        )
        return ToolOutput(status=ToolStatus.ok, idempotent_replay=True, data=data)

    filed_at = datetime.now(timezone.utc)
    data = FileDocumentData(
        coi_document_id=doc.id,
        is_current=doc.is_current,
        superseded_document_id=superseded_id,
        filed_at=filed_at,
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
                name="file_document.filed",
                severity=EventSeverity.info,
                tool_name=TOOL_NAME,
                idempotency_key=idempotency_key,
                payload={"coi_document_id": str(doc.id), "superseded": str(superseded_id) if superseded_id else None},
            )
        ],
    )
