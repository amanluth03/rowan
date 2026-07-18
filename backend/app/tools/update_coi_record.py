"""`update_coi_record` (ADR 0004 #3). Read mode first (build order per
CLAUDE.md), then write mode.

Read mode has no side effect and needs no idempotency key or budget check —
it's the read-only tool `update_coi_record read path` the build brief calls
out to build before any write-action tool.

Write mode persists the DETERMINISTIC validation result (`app.tools.
validation_logic.evaluate_validation`) as a `coi_validations` row. The LLM
never decides pass/fail — it only produced the `ExtractedCoiFields` that
feeds this comparison (agent-engineer's `parse_document`).
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

import asyncpg
from pydantic import BaseModel

from app.ids import uuid7
from app.models.coi_fields import ExtractedCoiFields
from app.models.enums import EventSeverity, EventType, ToolStatus
from app.models.tool_contracts import PendingEvent, ToolContext, ToolOutput
from app.retrieval import entity_repo
from app.retrieval.models import CoiDocumentRow, CoiValidationRow, VendorCoverageRequirementRow
from app.tools import idempotency, keys
from app.tools.validation_logic import evaluate_validation

TOOL_NAME = "update_coi_record"


# --------------------------------------------------------------------------
# Read mode
# --------------------------------------------------------------------------


class UpdateCoiRecordReadData(BaseModel):
    vendor_id: UUID
    requirements: list[VendorCoverageRequirementRow]
    current_document: CoiDocumentRow | None
    history: list[CoiDocumentRow]


async def read_coi_record(
    conn: asyncpg.Connection, *, vendor_id: UUID
) -> ToolOutput[UpdateCoiRecordReadData]:
    requirements = await entity_repo.get_vendor_coverage_requirements(conn, vendor_id)
    current = await entity_repo.get_current_coi_document(conn, vendor_id)
    history = await entity_repo.list_coi_document_history(conn, vendor_id)

    return ToolOutput(
        status=ToolStatus.ok,
        data=UpdateCoiRecordReadData(
            vendor_id=vendor_id,
            requirements=requirements,
            current_document=current,
            history=history,
        ),
    )


# --------------------------------------------------------------------------
# Write mode
# --------------------------------------------------------------------------


class UpdateCoiRecordWriteInput(BaseModel):
    coi_extraction_id: UUID
    confidence_threshold: float
    # qa-evals-engineer finding #4 (2026-07-18): must be explicitly supplied
    # by the caller (orchestration's own frozen `now`), not silently
    # defaulted to wall-clock date.today() — see evaluate_validation's own
    # `as_of` parameter in app/tools/validation_logic.py. None is preserved
    # as a fallback for callers/tests that genuinely want "real today" (it
    # falls through to validation_logic's own `as_of or date.today()`), but
    # app/orchestration/runner.py always passes one explicitly now.
    as_of: date | None = None


class UpdateCoiRecordWriteData(BaseModel):
    validation_id: UUID
    result: str
    line_results: list[dict]
    flags: list[dict]
    faithfulness_ok: bool
    no_requirements_on_file: bool


async def write_coi_record(
    conn: asyncpg.Connection, context: ToolContext, input: UpdateCoiRecordWriteInput
) -> ToolOutput[UpdateCoiRecordWriteData]:
    # ADR 0004: idempotency key = sha256(coi_extraction_id | 'validate') —
    # derived here, not trusted from the caller's context.idempotency_key,
    # so two orchestration calls for the same extraction always dedupe
    # regardless of what the caller passed.
    idempotency_key = keys.validate_key(input.coi_extraction_id)
    request_hash = keys.sha256(f"{input.coi_extraction_id}|{input.confidence_threshold}")

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
                data=UpdateCoiRecordWriteData(**outcome.stored_response),
            )
        if outcome.replay:
            return ToolOutput(
                status=ToolStatus.failed,
                idempotent_replay=True,
                reason="prior attempt failed; see tool_invocations.error",
            )
        return ToolOutput(status=ToolStatus.denied, reason="invocation already in progress")

    extraction = await entity_repo.get_extraction(conn, input.coi_extraction_id)
    if extraction is None:
        await idempotency.complete(
            conn, outcome.invocation_id, status="failed", error={"reason": "extraction_not_found"}
        )
        return ToolOutput(status=ToolStatus.failed, reason="coi_extraction not found")

    document = await entity_repo.get_coi_document(conn, extraction.coi_document_id)
    if document is None:
        await idempotency.complete(
            conn, outcome.invocation_id, status="failed", error={"reason": "document_not_found"}
        )
        return ToolOutput(status=ToolStatus.failed, reason="coi_document not found")

    requirements = await entity_repo.get_vendor_coverage_requirements(conn, document.vendor_id)

    active_kb_ids: set[UUID] = set()
    for req in requirements:
        if req.source_compliance_requirement_id is None:
            continue
        kb_row = await entity_repo.get_compliance_requirement(
            conn, req.source_compliance_requirement_id
        )
        if kb_row is not None and kb_row.active:
            active_kb_ids.add(kb_row.id)

    fields = ExtractedCoiFields.model_validate(extraction.extracted)

    result = evaluate_validation(
        requirements=requirements,
        extraction=fields,
        active_kb_ids=active_kb_ids,
        confidence_threshold=input.confidence_threshold,
        as_of=input.as_of,
    )

    validation_row: CoiValidationRow = await entity_repo.insert_coi_validation(
        conn,
        id=uuid7(),
        organization_id=context.organization_id,
        run_id=context.run_id,
        coi_extraction_id=input.coi_extraction_id,
        result=result.result,
        line_results=result.line_results,
        flags=result.flags,
        faithfulness_ok=result.faithfulness_ok,
    )

    data = UpdateCoiRecordWriteData(
        validation_id=validation_row.id,
        result=result.result,
        line_results=result.line_results,
        flags=result.flags,
        faithfulness_ok=result.faithfulness_ok,
        no_requirements_on_file=result.no_requirements_on_file,
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
                name="update_coi_record.validated",
                severity=EventSeverity.info if result.result == "pass" else EventSeverity.warn,
                tool_name=TOOL_NAME,
                idempotency_key=idempotency_key,
                payload={"result": result.result, "faithfulness_ok": result.faithfulness_ok},
            )
        ],
    )
