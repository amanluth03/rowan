"""Interface-layer (layer 1) wire schemas: the 9 ADR 0003 commands (typed
request -> orchestration call -> typed response) and the 4 read-model DTOs
(`RunTraceDTO`, `ActivityFeedItemDTO`, `VendorStatusDTO`, `ReviewQueueItemDTO`).

Every model here is JSON-schema-validated at the API edge (ADR 0003:
"Validated (Pydantic) at the API edge") and serializes camelCase over the
wire via `CamelModel`, matching the shape frontend-engineer already proposed
in `frontend/src/lib/types.ts` (flagged there as a proposal, not a ratified
contract — see this module's docstring notes below and the PR report for the
handful of places this implementation's real data can't match that shape
exactly).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.models.enums import (
    CoverageType,
    DocSource,
    DocStatus,
    EscalationKind,
    EscalationStatus,
    EventSeverity,
    EventType,
    RunState,
    RunStatus,
    VendorRole,
)


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---------------------------------------------------------------------------
# Auth: organization bootstrap (app/api/auth_routes.py)
# ---------------------------------------------------------------------------


class BootstrapOrgRequest(CamelModel):
    organization_name: str = Field(min_length=1, max_length=200)
    full_name: str | None = Field(default=None, max_length=200)


class BootstrapOrgResponse(CamelModel):
    organization_id: UUID
    user_id: UUID


# ---------------------------------------------------------------------------
# Commands: AddVendor, SetRequirements
# ---------------------------------------------------------------------------


class AddVendorRequest(CamelModel):
    name: str = Field(min_length=1, max_length=200)
    primary_email: str | None = None
    vendor_role: VendorRole
    primary_property_id: UUID | None = None
    notes: str | None = None
    # The current COI's known expiry, if any (PM-supplied at onboarding;
    # CLAUDE.md non-goals exclude auto-detection/OCR/bulk-import in v1). If
    # omitted, the run starts in `monitoring` with `due_date=NULL` — see
    # app/orchestration/runner.py::add_vendor's docstring.
    due_date: date | None = None


class AddVendorResponse(CamelModel):
    vendor_id: UUID
    run_id: UUID
    run_state: RunState
    reply_token: str
    reply_token_expires_at: datetime


class RequirementLineInput(CamelModel):
    coverage_type: CoverageType
    min_each_occurrence: int | None = None
    min_aggregate: int | None = None
    requires_additional_insured: bool = False
    requires_waiver_of_subrogation: bool = False
    requires_primary_noncontributory: bool = False
    # None => PM-entered override with no KB backing (flagged by the
    # validator as `unverified_requirement` per ADR 0001's # ASSUMPTION on
    # this column). If provided, must reference an existing, active
    # compliance_requirements row in the caller's org.
    source_compliance_requirement_id: UUID | None = None


class SetRequirementsRequest(CamelModel):
    # Omit (or null) to auto-retrieve from the compliance_requirements KB via
    # the vendor's primary_property_id jurisdiction context (ADR 0005). A
    # 422 with a clear message is returned if retrieval finds nothing — this
    # command NEVER materializes guessed requirements.
    lines: list[RequirementLineInput] | None = None


class RequirementLineDTO(CamelModel):
    vendor_coverage_requirement_id: UUID
    coverage_type: CoverageType
    min_each_occurrence: int | None
    min_aggregate: int | None
    requires_additional_insured: bool
    requires_waiver_of_subrogation: bool
    requires_primary_noncontributory: bool
    source_compliance_requirement_id: UUID | None
    source_citation: str | None
    source_url: str | None
    last_verified_at: datetime | None
    confirmed_by_pm: bool


class SetRequirementsResponse(CamelModel):
    vendor_id: UUID
    requirements: list[RequirementLineDTO]


# ---------------------------------------------------------------------------
# Commands: StartRun, PauseRun, ResumeRun
# ---------------------------------------------------------------------------


class RunActionResponse(CamelModel):
    run_id: UUID
    state: RunState
    status: RunStatus


# ---------------------------------------------------------------------------
# Commands: ApproveReview, RejectReview, RequestRevision, ResolveEscalation
# ---------------------------------------------------------------------------


class ApproveReviewRequest(CamelModel):
    # No `resolved_by` field. Attribution for this consequential action comes
    # ONLY from the authenticated principal (app.api.deps.get_principal) —
    # never a client-supplied value. See app/api/commands.py::approve_review.
    pass


class RejectReviewRequest(CamelModel):
    # No `resolved_by` field — see ApproveReviewRequest.
    pass


class RequestRevisionRequest(CamelModel):
    # No `resolved_by` field — see ApproveReviewRequest.
    revision_reason: str | None = None


class ResolveEscalationRequest(CamelModel):
    decision: Literal["resolved", "keep_chasing"]
    # No `resolved_by` field — see ApproveReviewRequest.


class ReviewActionResponse(CamelModel):
    escalation_id: UUID
    run_id: UUID
    run_state: RunState


# ---------------------------------------------------------------------------
# Shared evidence primitives (mirrors frontend/src/lib/types.ts)
# ---------------------------------------------------------------------------


class DocumentRef(CamelModel):
    document_id: UUID
    url: str
    filename: str
    content_type: str
    version_number: int


class ParsedLineDTO(CamelModel):
    coverage_type: CoverageType
    each_occurrence: int | None
    aggregate: int | None
    additional_insured: bool | None
    waiver_of_subrogation: bool | None
    primary_noncontributory: bool | None
    confidence: float | None


class LineComparisonDTO(CamelModel):
    coverage_type: CoverageType
    required: RequirementLineDTO
    parsed: ParsedLineDTO | None
    pass_: bool = Field(alias="pass")
    severity: EventSeverity
    note: str | None


class FlagDTO(CamelModel):
    code: str
    message: str
    severity: EventSeverity


# ---------------------------------------------------------------------------
# ActivityFeedItemDTO
# ---------------------------------------------------------------------------

ActivityFeedItemKind = Literal[
    "run_filed",
    "outreach_sent",
    "follow_up_sent",
    "document_received",
    "validation_failed",
    "needs_human_review",
    "escalated_to_pm",
    "human_resolved",
    "renewal_due_soon",
]


class ActivityFeedEvidence(CamelModel):
    document: DocumentRef | None
    valid_to: date | None
    source_citation: str | None


class ActivityFeedItemDTO(CamelModel):
    id: UUID
    run_id: UUID
    vendor_id: UUID
    vendor_name: str
    vendor_role: VendorRole
    kind: ActivityFeedItemKind
    headline: str
    detail: str | None
    state: RunState
    severity: EventSeverity
    occurred_at: datetime
    action_required: bool
    evidence: ActivityFeedEvidence


# ---------------------------------------------------------------------------
# VendorStatusDTO
# ---------------------------------------------------------------------------

ComplianceStatus = Literal[
    "compliant", "expiring_soon", "needs_review", "escalated", "no_requirements", "pending"
]


class CoiHistoryItemDTO(CamelModel):
    document: DocumentRef
    status: DocStatus
    valid_from: date | None
    valid_to: date | None
    is_current: bool
    received_at: datetime
    source: DocSource


class CurrentCoiDTO(CamelModel):
    document: DocumentRef
    valid_from: date
    valid_to: date
    # # ASSUMPTION / DTO mismatch (flagged for frontend-engineer, see PR
    # report): `coi_documents` has no separate `filed_at` column (ADR 0001).
    # This is approximated as `received_at` — the closest timestamp actually
    # on the row — not the moment `file_document` flipped `is_current`.
    filed_at: datetime


class ActiveRunSummaryDTO(CamelModel):
    run_id: UUID
    state: RunState
    status: RunStatus
    due_date: date | None
    next_action_at: datetime | None
    outreach_email_count: int
    max_outreach: int


class VendorStatusDTO(CamelModel):
    id: UUID
    organization_id: UUID
    name: str
    role: VendorRole
    primary_email: str | None
    status: Literal["active", "inactive"]
    primary_property_name: str | None
    primary_property_jurisdiction: str | None
    compliance_status: ComplianceStatus
    current_coi: CurrentCoiDTO | None
    requirements: list[RequirementLineDTO]
    active_run: ActiveRunSummaryDTO | None
    history: list[CoiHistoryItemDTO]


# ---------------------------------------------------------------------------
# RunTraceDTO
# ---------------------------------------------------------------------------


class AgentEventDTO(CamelModel):
    id: UUID
    type: EventType
    name: str
    severity: EventSeverity
    from_state: RunState | None
    to_state: RunState | None
    tool_name: str | None
    llm_model: str | None
    prompt_hash: str | None
    input_tokens: int | None
    output_tokens: int | None
    cost_cents: int | None
    latency_ms: int | None
    payload: dict[str, Any]
    created_at: datetime


class RunBudgetDTO(CamelModel):
    outreach_email_count: int
    max_outreach: int
    llm_call_count: int
    max_llm_calls_per_doc: int
    cost_cents_spent: int
    budget_cost_cap_cents: int


class RunTraceDTO(CamelModel):
    run_id: UUID
    vendor_id: UUID
    vendor_name: str
    vendor_role: VendorRole
    state: RunState
    status: RunStatus
    trigger: Literal["renewal_due", "manual"]
    due_date: date | None
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    budget: RunBudgetDTO
    events: list[AgentEventDTO]


# ---------------------------------------------------------------------------
# ReviewQueueItemDTO
# ---------------------------------------------------------------------------


class ReviewQueueItemDTO(CamelModel):
    escalation_id: UUID
    run_id: UUID
    vendor_id: UUID
    vendor_name: str
    vendor_role: VendorRole
    kind: EscalationKind
    reason_code: str
    severity: EventSeverity
    summary: str
    status: EscalationStatus
    created_at: datetime
    document: DocumentRef | None
    comparison: list[LineComparisonDTO]
    flags: list[FlagDTO]
    faithfulness_ok: bool
    overall_confidence: float | None
