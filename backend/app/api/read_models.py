"""Read-model assembly (ADR 0003 "Orchestration -> Interface: read-model
DTOs"). Assembles the four DTOs from the retrieval layer + `agent_events`,
carrying evidence refs (document url, parsed values, `source_citation`) per
CLAUDE.md's brand section ("every claim in the UI carries evidence").

This module is the "read-model service" ADR 0003's boundary rule #3 calls
out as the one legitimate way the Interface layer's read paths reach
Retrieval: "Read-only DTO assembly may query retrieval, but through a
read-model service, not ad-hoc SQL in a route." app/api/reads.py (the FastAPI
routes) calls only the functions in this module — never entity_repo/run_repo
directly.
"""

from __future__ import annotations

from datetime import date as date_cls
from typing import Any
from uuid import UUID

from app.db import org_scoped_tx
from app.models.enums import EventSeverity, RunState
from app.orchestration.constants import resolve_constants
from app.retrieval import entity_repo, run_repo
from app.retrieval.models import (
    AgentEventRow,
    CoiDocumentRow,
    ComplianceRequirementRow,
    EscalationRow,
    RunRow,
    VendorCoverageRequirementRow,
    VendorRow,
)
from app.api.schemas import (
    ActiveRunSummaryDTO,
    ActivityFeedEvidence,
    ActivityFeedItemDTO,
    AgentEventDTO,
    CoiHistoryItemDTO,
    CurrentCoiDTO,
    DocumentRef,
    FlagDTO,
    LineComparisonDTO,
    ParsedLineDTO,
    RequirementLineDTO,
    ReviewQueueItemDTO,
    RunBudgetDTO,
    RunTraceDTO,
    VendorStatusDTO,
)


def _dto_severity(raw: str | None) -> EventSeverity:
    """`validation_logic.py`'s `flags`/`line_results` entries use a
    'high'/'info' severity vocabulary (document-review triage), not
    `EventSeverity`'s 'info'/'warn'/'error' (ADR 0001's agent_events/
    escalations vocabulary) — a real shape mismatch between the two, not an
    oversight. Mapped here rather than changing validation_logic.py's
    established vocabulary (qa-evals-engineer's fixtures already assert
    'high'/'info' verbatim; see tests/test_validation_logic.py) or
    ADR 0001's enum (binding). Flagged for frontend-engineer: `LineComparisonDTO.severity`
    and `FlagDTO.severity` only ever take the values 'info' or 'error' in
    practice, never 'warn' — a coarser mapping than EventSeverity's full range.
    """
    return EventSeverity.error if raw == "high" else EventSeverity.info


def document_download_url(document_id: UUID) -> str:
    return f"/api/v1/documents/{document_id}/download"


def _document_ref(doc: CoiDocumentRow) -> DocumentRef:
    return DocumentRef(
        document_id=doc.id,
        url=document_download_url(doc.id),
        filename=doc.original_filename,
        content_type=doc.content_type,
        version_number=doc.version_number,
    )


def _requirement_line_dto(
    vcr: VendorCoverageRequirementRow, kb: ComplianceRequirementRow | None
) -> RequirementLineDTO:
    return RequirementLineDTO(
        vendor_coverage_requirement_id=vcr.id,
        coverage_type=vcr.coverage_type,
        min_each_occurrence=vcr.min_each_occurrence,
        min_aggregate=vcr.min_aggregate,
        requires_additional_insured=vcr.requires_additional_insured,
        requires_waiver_of_subrogation=vcr.requires_waiver_of_subrogation,
        requires_primary_noncontributory=vcr.requires_primary_noncontributory,
        source_compliance_requirement_id=vcr.source_compliance_requirement_id,
        source_citation=kb.source_citation if kb else None,
        source_url=kb.source_url if kb else None,
        last_verified_at=kb.last_verified_at if kb else None,
        confirmed_by_pm=vcr.confirmed_by_pm,
    )


async def _requirement_line_dtos(conn, vendor_id: UUID) -> list[RequirementLineDTO]:
    vcrs = await entity_repo.get_vendor_coverage_requirements(conn, vendor_id)
    out: list[RequirementLineDTO] = []
    for vcr in vcrs:
        kb = None
        if vcr.source_compliance_requirement_id is not None:
            kb = await entity_repo.get_compliance_requirement(conn, vcr.source_compliance_requirement_id)
        out.append(_requirement_line_dto(vcr, kb))
    return out


def _compliance_status(
    run: RunRow | None, requirements: list[RequirementLineDTO], current_doc: CoiDocumentRow | None
) -> str:
    if not requirements:
        return "no_requirements"
    if run is None:
        return "pending"
    if run.state == RunState.escalated_to_pm:
        return "escalated"
    if run.state == RunState.needs_human_review:
        return "needs_review"
    if run.state in (
        RunState.renewal_due_soon,
        RunState.first_outreach_sent,
        RunState.awaiting_vendor_response,
        RunState.document_received,
        RunState.parsing,
        RunState.validating,
    ):
        return "expiring_soon"
    if run.state == RunState.monitoring and current_doc is not None:
        return "compliant"
    return "pending"


async def _assemble_vendor_status(conn, vendor: VendorRow, *, max_outreach: int) -> VendorStatusDTO:
    prop = None
    if vendor.primary_property_id is not None:
        prop = await entity_repo.get_property(conn, vendor.primary_property_id)

    requirements = await _requirement_line_dtos(conn, vendor.id)
    current_doc = await entity_repo.get_current_coi_document(conn, vendor.id)
    active_run = await run_repo.get_active_run_for_vendor(conn, vendor.id)
    history_rows = await entity_repo.list_coi_document_history(conn, vendor.id)

    return VendorStatusDTO(
        id=vendor.id,
        organization_id=vendor.organization_id,
        name=vendor.name,
        role=vendor.vendor_role,
        primary_email=vendor.primary_email,
        status=vendor.status.value,
        primary_property_name=prop.name if prop else None,
        primary_property_jurisdiction=(f"{prop.city}, {prop.state}" if prop else None),
        compliance_status=_compliance_status(active_run, requirements, current_doc),
        current_coi=(
            CurrentCoiDTO(
                document=_document_ref(current_doc),
                valid_from=current_doc.valid_from,
                valid_to=current_doc.valid_to,
                filed_at=current_doc.received_at,
            )
            if current_doc and current_doc.valid_from and current_doc.valid_to
            else None
        ),
        requirements=requirements,
        active_run=(
            ActiveRunSummaryDTO(
                run_id=active_run.id,
                state=active_run.state,
                status=active_run.status,
                due_date=active_run.due_date,
                next_action_at=active_run.next_action_at,
                outreach_email_count=active_run.outreach_email_count,
                max_outreach=max_outreach,
            )
            if active_run
            else None
        ),
        history=[
            CoiHistoryItemDTO(
                document=_document_ref(d),
                status=d.status,
                valid_from=d.valid_from,
                valid_to=d.valid_to,
                is_current=d.is_current,
                received_at=d.received_at,
                source=d.source,
            )
            for d in history_rows
        ],
    )


async def requirement_lines_to_dtos(
    organization_id: UUID, vcrs: list[VendorCoverageRequirementRow]
) -> list[RequirementLineDTO]:
    """Public helper so app/api/commands.py's SetRequirements response can
    shape its output through the read-model service (ADR 0003 boundary rule
    #3: "Read-only DTO assembly may query retrieval, but through a
    read-model service, not ad-hoc SQL in a route") instead of importing
    entity_repo directly in a route handler."""
    async with org_scoped_tx(organization_id) as conn:
        out: list[RequirementLineDTO] = []
        for vcr in vcrs:
            kb = None
            if vcr.source_compliance_requirement_id is not None:
                kb = await entity_repo.get_compliance_requirement(conn, vcr.source_compliance_requirement_id)
            out.append(_requirement_line_dto(vcr, kb))
        return out


async def get_vendor_status(organization_id: UUID, vendor_id: UUID) -> VendorStatusDTO | None:
    async with org_scoped_tx(organization_id) as conn:
        vendor = await entity_repo.get_vendor(conn, vendor_id)
        if vendor is None:
            return None
        org = await entity_repo.get_organization(conn, organization_id)
        constants = resolve_constants(org.settings if org else None)
        return await _assemble_vendor_status(conn, vendor, max_outreach=constants.max_outreach)


async def list_vendor_statuses(organization_id: UUID) -> list[VendorStatusDTO]:
    async with org_scoped_tx(organization_id) as conn:
        vendors = await entity_repo.list_vendors(conn)
        org = await entity_repo.get_organization(conn, organization_id)
        constants = resolve_constants(org.settings if org else None)
        return [await _assemble_vendor_status(conn, v, max_outreach=constants.max_outreach) for v in vendors]


# ---------------------------------------------------------------------------
# RunTraceDTO
# ---------------------------------------------------------------------------


def _agent_event_dto(e: AgentEventRow) -> AgentEventDTO:
    return AgentEventDTO(
        id=e.id,
        type=e.event_type,
        name=e.name,
        severity=e.severity,
        from_state=e.from_state,
        to_state=e.to_state,
        tool_name=e.tool_name,
        llm_model=e.llm_model,
        prompt_hash=e.prompt_hash,
        input_tokens=e.input_tokens,
        output_tokens=e.output_tokens,
        cost_cents=e.cost_cents,
        latency_ms=e.latency_ms,
        payload=e.payload,
        created_at=e.created_at,
    )


async def get_run_trace(organization_id: UUID, run_id: UUID) -> RunTraceDTO | None:
    async with org_scoped_tx(organization_id) as conn:
        run = await run_repo.get_run(conn, run_id)
        if run is None:
            return None
        vendor = await entity_repo.get_vendor(conn, run.vendor_id)
        events = await entity_repo.list_agent_events_for_run(conn, run_id)
        org = await entity_repo.get_organization(conn, organization_id)
        constants = resolve_constants(org.settings if org else None)

    return RunTraceDTO(
        run_id=run.id,
        vendor_id=run.vendor_id,
        vendor_name=vendor.name if vendor else "",
        vendor_role=vendor.vendor_role if vendor else None,
        state=run.state,
        status=run.status,
        trigger=run.trigger,
        due_date=run.due_date,
        started_at=run.started_at,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
        budget=RunBudgetDTO(
            outreach_email_count=run.outreach_email_count,
            max_outreach=constants.max_outreach,
            llm_call_count=run.llm_call_count,
            max_llm_calls_per_doc=constants.max_llm_per_doc,
            cost_cents_spent=run.cost_cents_spent,
            budget_cost_cap_cents=run.budget_cost_cap_cents,
        ),
        events=[_agent_event_dto(e) for e in events],
    )


# ---------------------------------------------------------------------------
# ActivityFeedItemDTO
# ---------------------------------------------------------------------------

# state_transition (to_state, payload.guard) -> (kind, action_required).
# Any (to_state, guard) combination not listed here is not feed-worthy
# (internal bookkeeping transitions like ->first_outreach_sent, ->parsing,
# ->validating) and is skipped.
#
# "run_filed" is keyed on `filed -> monitoring` (guard
# "filed_and_cycle_reset", app/orchestration/runner.py::complete_filing) —
# NOT on entering the `filed` state — because that transition is where
# `file_document` + `mark_task_complete` + the PM "handled" notice actually
# happen (CLAUDE.md's hero example, "Renewed COI for Hernandez Plumbing --
# valid through 3/2027 -- filed", describes a DONE cycle, not the
# intermediate validating->filed hop).
_TRANSITION_FEED_KIND: dict[tuple[str, str | None], tuple[str, bool]] = {
    ("renewal_due_soon", "due_date_within_lead_window"): ("renewal_due_soon", False),
    ("renewal_due_soon", "manual_start"): ("renewal_due_soon", False),
    ("awaiting_vendor_response", "send_email_returned_provider_id"): ("outreach_sent", False),
    ("awaiting_vendor_response", "followup_within_budget"): ("follow_up_sent", False),
    ("awaiting_vendor_response", "pm_requested_revision"): ("follow_up_sent", False),
    ("awaiting_vendor_response", "pm_keep_chasing"): ("follow_up_sent", False),
    ("document_received", "valid_attachment_inbound"): ("document_received", False),
    ("needs_human_review", "validation_failed"): ("validation_failed", True),
    ("needs_human_review", "unclassifiable_document"): ("needs_human_review", True),
    ("needs_human_review", "low_confidence_extraction"): ("needs_human_review", True),
    ("needs_human_review", "extraction_budget_exhausted"): ("needs_human_review", True),
    ("monitoring", "filed_and_cycle_reset"): ("run_filed", False),
}


def _feed_headline(kind: str, vendor_name: str, *, valid_to: str | None, reason: str | None) -> str:
    if kind == "run_filed":
        suffix = f" — valid through {valid_to}" if valid_to else ""
        return f"Renewed COI for {vendor_name}{suffix} — filed."
    if kind == "outreach_sent":
        return f"Requested a COI renewal from {vendor_name}."
    if kind == "follow_up_sent":
        return f"Followed up with {vendor_name} about their COI renewal."
    if kind == "document_received":
        return f"Received a document from {vendor_name}."
    if kind == "validation_failed":
        return f"{vendor_name}'s certificate did not pass automated coverage validation — needs review."
    if kind == "needs_human_review":
        return f"{vendor_name}'s certificate needs human review."
    if kind == "escalated_to_pm":
        return f"Escalated {vendor_name} to you" + (f": {reason}" if reason else ".")
    if kind == "human_resolved":
        return f"You resolved an item for {vendor_name}."
    if kind == "renewal_due_soon":
        return f"{vendor_name}'s COI renewal is coming due."
    return f"Update for {vendor_name}."


async def _feed_item_from_event(
    conn, event: AgentEventRow, *, vendor_cache: dict[UUID, VendorRow], doc_cache: dict[UUID, CoiDocumentRow]
) -> ActivityFeedItemDTO | None:
    if event.vendor_id is None or event.run_id is None:
        return None

    kind: str | None = None
    action_required = False

    if event.event_type.value == "human_intervention":
        kind, action_required = "human_resolved", False
    elif event.event_type.value == "state_transition" and event.to_state is not None:
        to_state = event.to_state.value
        guard = event.payload.get("guard")
        if to_state == "escalated_to_pm":
            kind, action_required = "escalated_to_pm", True
        else:
            mapped = _TRANSITION_FEED_KIND.get((to_state, guard))
            if mapped:
                kind, action_required = mapped

    if kind is None:
        return None

    if event.vendor_id not in vendor_cache:
        vendor_cache[event.vendor_id] = await entity_repo.get_vendor(conn, event.vendor_id)
    vendor = vendor_cache[event.vendor_id]
    if vendor is None:
        return None

    document_ref = None
    valid_to: date_cls | None = None
    source_citation = None

    if kind == "document_received" and event.payload.get("coi_document_id"):
        doc_id = UUID(event.payload["coi_document_id"])
        if doc_id not in doc_cache:
            doc_cache[doc_id] = await entity_repo.get_coi_document(conn, doc_id)
        doc = doc_cache[doc_id]
        if doc:
            document_ref = _document_ref(doc)
    elif kind == "run_filed":
        doc = await entity_repo.get_current_coi_document(conn, event.vendor_id)
        if doc:
            document_ref = _document_ref(doc)
            valid_to = doc.valid_to

    headline = _feed_headline(
        kind,
        vendor.name,
        valid_to=valid_to.isoformat() if valid_to else None,
        reason=event.payload.get("reason") or event.payload.get("reason_code"),
    )

    return ActivityFeedItemDTO(
        id=event.id,
        run_id=event.run_id,
        vendor_id=event.vendor_id,
        vendor_name=vendor.name,
        vendor_role=vendor.vendor_role,
        kind=kind,
        headline=headline,
        detail=event.payload.get("reason") if isinstance(event.payload.get("reason"), str) else None,
        state=event.to_state or RunState.monitoring,
        severity=event.severity,
        occurred_at=event.created_at,
        action_required=action_required,
        evidence=ActivityFeedEvidence(
            document=document_ref,
            valid_to=valid_to,
            source_citation=source_citation,
        ),
    )


async def list_activity_feed(organization_id: UUID, *, limit: int = 50) -> list[ActivityFeedItemDTO]:
    async with org_scoped_tx(organization_id) as conn:
        raw_events = await entity_repo.list_recent_agent_events_for_org(conn, limit=max(limit * 5, 100))
        vendor_cache: dict[UUID, VendorRow] = {}
        doc_cache: dict[UUID, CoiDocumentRow] = {}
        items: list[ActivityFeedItemDTO] = []
        for event in raw_events:
            item = await _feed_item_from_event(conn, event, vendor_cache=vendor_cache, doc_cache=doc_cache)
            if item is not None:
                items.append(item)
            if len(items) >= limit:
                break
    return items


# ---------------------------------------------------------------------------
# ReviewQueueItemDTO
# ---------------------------------------------------------------------------


async def _line_comparison_dto(
    conn, line_result: dict[str, Any], vcr_by_id: dict[str, VendorCoverageRequirementRow]
) -> LineComparisonDTO | None:
    vcr_id = line_result.get("vendor_coverage_requirement_id")
    vcr = vcr_by_id.get(vcr_id) if vcr_id else None
    if vcr is None:
        return None

    kb = None
    source_id = line_result.get("source_compliance_requirement_id")
    if source_id:
        kb = await entity_repo.get_compliance_requirement(conn, UUID(source_id))

    required = _requirement_line_dto(vcr, kb)
    parsed_raw = line_result.get("parsed")
    parsed = (
        ParsedLineDTO(
            coverage_type=line_result["coverage_type"],
            each_occurrence=parsed_raw.get("each_occurrence"),
            aggregate=parsed_raw.get("aggregate"),
            additional_insured=parsed_raw.get("additional_insured"),
            waiver_of_subrogation=parsed_raw.get("waiver_of_subrogation"),
            primary_noncontributory=parsed_raw.get("primary_noncontributory"),
            confidence=parsed_raw.get("confidence"),
        )
        if parsed_raw
        else None
    )

    return LineComparisonDTO(
        coverage_type=line_result["coverage_type"],
        required=required,
        parsed=parsed,
        pass_=bool(line_result.get("pass")),
        severity=_dto_severity(line_result.get("severity")),
        note=", ".join(line_result.get("reasons", [])) or None,
    )


async def _assemble_review_queue_item(conn, esc: EscalationRow) -> ReviewQueueItemDTO:
    vendor = await entity_repo.get_vendor(conn, esc.vendor_id)
    run = await run_repo.get_run(conn, esc.run_id)

    document = None
    comparison: list[LineComparisonDTO] = []
    flags: list[FlagDTO] = []
    faithfulness_ok = True
    overall_confidence = None

    if run is not None and run.coi_document_id is not None:
        doc = await entity_repo.get_coi_document(conn, run.coi_document_id)
        if doc is not None:
            document = _document_ref(doc)
        extraction = await entity_repo.get_current_extraction(conn, run.coi_document_id)
        if extraction is not None:
            overall_confidence = extraction.overall_confidence
            validation = await entity_repo.get_latest_validation_for_extraction(conn, extraction.id)
            if validation is not None:
                faithfulness_ok = validation.faithfulness_ok
                flags = [
                    FlagDTO(
                        code=f.get("code", "?"),
                        message=f.get("message", ""),
                        severity=_dto_severity(f.get("severity")),
                    )
                    for f in validation.flags
                ]
                vcr_rows = await entity_repo.get_vendor_coverage_requirements(conn, esc.vendor_id)
                vcr_by_id = {str(v.id): v for v in vcr_rows}
                for lr in validation.line_results:
                    dto = await _line_comparison_dto(conn, lr, vcr_by_id)
                    if dto is not None:
                        comparison.append(dto)

    if not flags and esc.details.get("flags"):
        flags = [
            FlagDTO(
                code=f.get("code", "?"),
                message=f.get("message", ""),
                severity=_dto_severity(f.get("severity")),
            )
            for f in esc.details["flags"]
        ]

    return ReviewQueueItemDTO(
        escalation_id=esc.id,
        run_id=esc.run_id,
        vendor_id=esc.vendor_id,
        vendor_name=vendor.name if vendor else "",
        vendor_role=vendor.vendor_role if vendor else None,
        kind=esc.kind,
        reason_code=esc.reason_code,
        severity=esc.severity,
        summary=esc.summary,
        status=esc.status,
        created_at=esc.created_at,
        document=document,
        comparison=comparison,
        flags=flags,
        faithfulness_ok=faithfulness_ok,
        overall_confidence=overall_confidence,
    )


async def list_review_queue(organization_id: UUID, *, kind: str | None = None) -> list[ReviewQueueItemDTO]:
    async with org_scoped_tx(organization_id) as conn:
        escalations = await entity_repo.list_open_escalations(conn, kind=kind)
        return [await _assemble_review_queue_item(conn, esc) for esc in escalations]


async def get_review_queue_item(organization_id: UUID, escalation_id: UUID) -> ReviewQueueItemDTO | None:
    async with org_scoped_tx(organization_id) as conn:
        esc = await entity_repo.get_escalation(conn, escalation_id)
        if esc is None:
            return None
        return await _assemble_review_queue_item(conn, esc)
