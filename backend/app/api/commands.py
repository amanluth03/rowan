"""Interface -> Orchestration commands (ADR 0003): the 9 typed commands —
`AddVendor`, `SetRequirements`, `StartRun`, `PauseRun`, `ResumeRun`,
`ApproveReview`, `RejectReview`, `RequestRevision`, `ResolveEscalation`.

Every route here does exactly three things: validate the request (Pydantic,
at the API edge), call ONE orchestration function (app/orchestration/runner.py
— never app/retrieval or app/tools directly, ADR 0003 hard rule #3), and
shape the typed response. No business rules, no state transitions, no
prompts live here (ADR 0003: "Contains no business rules, no state
transitions, no prompts").
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api import read_models
from app.api.deps import Principal, get_organization_id, get_principal, rate_limit, require_role
from app.api.schemas import (
    AddVendorRequest,
    AddVendorResponse,
    ApproveReviewRequest,
    RejectReviewRequest,
    RequestRevisionRequest,
    ResolveEscalationRequest,
    ReviewActionResponse,
    RunActionResponse,
    SetRequirementsRequest,
    SetRequirementsResponse,
)
from app.orchestration import runner
from app.policy.permissions import Command

router = APIRouter(prefix="/api/v1", tags=["commands"], dependencies=[Depends(rate_limit)])


# ---------------------------------------------------------------------------
# AddVendor, SetRequirements — vendor onboarding
# ---------------------------------------------------------------------------


@router.post(
    "/vendors",
    response_model=AddVendorResponse,
    status_code=201,
    dependencies=[Depends(require_role(Command.add_vendor))],
)
async def add_vendor(
    body: AddVendorRequest, organization_id: UUID = Depends(get_organization_id)
) -> AddVendorResponse:
    try:
        vendor, run = await runner.add_vendor(
            organization_id,
            name=body.name,
            primary_email=body.primary_email,
            vendor_role=body.vendor_role.value,
            primary_property_id=body.primary_property_id,
            notes=body.notes,
            due_date=body.due_date,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    return AddVendorResponse(
        vendor_id=vendor.id,
        run_id=run.id,
        run_state=run.state,
        reply_token=run.reply_token,
        reply_token_expires_at=run.reply_token_expires_at,
    )


@router.post(
    "/vendors/{vendor_id}/requirements",
    response_model=SetRequirementsResponse,
    dependencies=[Depends(require_role(Command.set_requirements))],
)
async def set_requirements(
    vendor_id: UUID,
    body: SetRequirementsRequest,
    organization_id: UUID = Depends(get_organization_id),
) -> SetRequirementsResponse:
    lines = (
        [line.model_dump(exclude_none=False) for line in body.lines] if body.lines is not None else None
    )
    try:
        vcrs = await runner.set_requirements(organization_id, vendor_id, lines=lines)
    except runner.NoRequirementsOnFileError as e:
        # ADR 0005 fallback, surfaced at onboarding time: never materialize a
        # guessed requirement set. 422 (not 404/500) — the request was valid,
        # the KB just has nothing for this jurisdiction/property/role yet.
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    dtos = await read_models.requirement_lines_to_dtos(organization_id, vcrs)
    return SetRequirementsResponse(vendor_id=vendor_id, requirements=dtos)


# ---------------------------------------------------------------------------
# StartRun, PauseRun, ResumeRun — run lifecycle / kill-switch-adjacent
# ---------------------------------------------------------------------------


@router.post(
    "/runs/{run_id}/start",
    response_model=RunActionResponse,
    dependencies=[Depends(require_role(Command.start_run))],
)
async def start_run(run_id: UUID, organization_id: UUID = Depends(get_organization_id)) -> RunActionResponse:
    run = await runner.start_run_now(organization_id, run_id)
    if run is None:
        raise HTTPException(
            status_code=409,
            detail="run not found, not in monitoring/renewal_due_soon, or frozen (paused/org-disabled/kill switch)",
        )
    return RunActionResponse(run_id=run.id, state=run.state, status=run.status)


@router.post(
    "/runs/{run_id}/pause",
    response_model=RunActionResponse,
    dependencies=[Depends(require_role(Command.pause_run))],
)
async def pause_run(
    run_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    paused_by: UUID | None = None,
) -> RunActionResponse:
    run = await runner.pause_run(organization_id, run_id, paused_by=paused_by)
    if run is None:
        raise HTTPException(status_code=409, detail="run not found or not active (already paused/completed/errored)")
    return RunActionResponse(run_id=run.id, state=run.state, status=run.status)


@router.post(
    "/runs/{run_id}/resume",
    response_model=RunActionResponse,
    dependencies=[Depends(require_role(Command.resume_run))],
)
async def resume_run(run_id: UUID, organization_id: UUID = Depends(get_organization_id)) -> RunActionResponse:
    run = await runner.resume_run(organization_id, run_id)
    if run is None:
        raise HTTPException(status_code=409, detail="run not found or not currently paused")
    return RunActionResponse(run_id=run.id, state=run.state, status=run.status)


# ---------------------------------------------------------------------------
# ApproveReview, RejectReview, RequestRevision — human-review queue
# (needs_human_review), wired to resolve_needs_human_review (runner.py)
# ---------------------------------------------------------------------------


@router.post(
    "/reviews/{escalation_id}/approve",
    response_model=ReviewActionResponse,
    dependencies=[Depends(require_role(Command.approve_review))],
)
async def approve_review(
    escalation_id: UUID,
    body: ApproveReviewRequest = ApproveReviewRequest(),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
) -> ReviewActionResponse:
    # The approver is the authenticated principal, never a client-supplied
    # value -- approving a COI is a consequential action (CLAUDE.md) and its
    # attribution must not be forgeable.
    run = await runner.approve_review(organization_id, escalation_id, resolved_by=principal.user_id)
    if run is None:
        raise HTTPException(status_code=409, detail="no open needs_human_review escalation with that id")
    return ReviewActionResponse(escalation_id=escalation_id, run_id=run.id, run_state=run.state)


@router.post(
    "/reviews/{escalation_id}/reject",
    response_model=ReviewActionResponse,
    dependencies=[Depends(require_role(Command.reject_review))],
)
async def reject_review(
    escalation_id: UUID,
    body: RejectReviewRequest = RejectReviewRequest(),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
) -> ReviewActionResponse:
    # The approver is the authenticated principal, never a client-supplied
    # value -- see approve_review above.
    run = await runner.reject_review(organization_id, escalation_id, resolved_by=principal.user_id)
    if run is None:
        raise HTTPException(status_code=409, detail="no open needs_human_review escalation with that id")
    return ReviewActionResponse(escalation_id=escalation_id, run_id=run.id, run_state=run.state)


@router.post(
    "/reviews/{escalation_id}/request-revision",
    response_model=ReviewActionResponse,
    dependencies=[Depends(require_role(Command.request_revision))],
)
async def request_revision(
    escalation_id: UUID,
    body: RequestRevisionRequest = RequestRevisionRequest(),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
) -> ReviewActionResponse:
    # The approver is the authenticated principal, never a client-supplied
    # value -- see approve_review above.
    run = await runner.request_revision(
        organization_id, escalation_id, resolved_by=principal.user_id, revision_reason=body.revision_reason
    )
    if run is None:
        raise HTTPException(status_code=409, detail="no open needs_human_review escalation with that id")
    return ReviewActionResponse(escalation_id=escalation_id, run_id=run.id, run_state=run.state)


# ---------------------------------------------------------------------------
# ResolveEscalation — the escalated_to_pm resolution path
# ---------------------------------------------------------------------------


@router.post(
    "/escalations/{escalation_id}/resolve",
    response_model=ReviewActionResponse,
    dependencies=[Depends(require_role(Command.resolve_escalation))],
)
async def resolve_escalation(
    escalation_id: UUID,
    body: ResolveEscalationRequest,
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
) -> ReviewActionResponse:
    # The approver is the authenticated principal, never a client-supplied
    # value -- see approve_review above.
    run = await runner.resolve_escalation(
        organization_id, escalation_id, decision=body.decision, resolved_by=principal.user_id
    )
    if run is None:
        raise HTTPException(status_code=409, detail="no open escalated_to_pm escalation with that id")
    return ReviewActionResponse(escalation_id=escalation_id, run_id=run.id, run_state=run.state)
