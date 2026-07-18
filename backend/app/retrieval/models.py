"""Typed rows returned by the retrieval layer.

Per ADR 0003: "Returns typed rows, never raw SQL or ORM objects, upward."
Every repository function in app/retrieval/*_repo.py returns one of these
(or a list of them) — callers never see an asyncpg.Record.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import (
    CoverageType,
    DocSource,
    DocStatus,
    EmailDirection,
    EscalationKind,
    EscalationStatus,
    EventSeverity,
    PropertyType,
    RunState,
    RunStatus,
    ValidationResult,
    VendorRole,
    VendorStatus,
)


class OrganizationRow(BaseModel):
    id: UUID
    name: str
    agent_enabled: bool
    settings: dict[str, Any]
    created_at: datetime


class PropertyRow(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    line1: str
    city: str
    state: str
    county: str | None
    postal_code: str
    country: str
    hoa_name: str | None
    property_type: PropertyType
    attributes: dict[str, Any]


class VendorRow(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    primary_email: str | None
    vendor_role: VendorRole
    status: VendorStatus
    primary_property_id: UUID | None
    notes: str | None


class VendorCoverageRequirementRow(BaseModel):
    id: UUID
    organization_id: UUID
    vendor_id: UUID
    coverage_type: CoverageType
    min_each_occurrence: int | None
    min_aggregate: int | None
    requires_additional_insured: bool
    requires_waiver_of_subrogation: bool
    requires_primary_noncontributory: bool
    source_compliance_requirement_id: UUID | None
    confirmed_by_pm: bool


class ComplianceRequirementRow(BaseModel):
    id: UUID
    organization_id: UUID
    jurisdiction_state: str
    jurisdiction_city: str | None
    jurisdiction_hoa: str | None
    property_type: PropertyType | None
    vendor_role: VendorRole | None
    coverage_type: CoverageType
    min_each_occurrence: int | None
    min_aggregate: int | None
    requires_additional_insured: bool
    requires_waiver_of_subrogation: bool
    requires_primary_noncontributory: bool
    source_citation: str
    source_url: str | None
    last_verified_at: datetime
    active: bool


class RunRow(BaseModel):
    id: UUID
    organization_id: UUID
    vendor_id: UUID
    coi_document_id: UUID | None
    state: RunState
    status: RunStatus
    trigger: str
    due_date: date | None
    next_action_at: datetime | None
    outreach_email_count: int
    llm_call_count: int
    cost_cents_spent: int
    budget_cost_cap_cents: int
    reply_token: str | None
    reply_token_expires_at: datetime | None
    paused_by: UUID | None
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class CoiDocumentRow(BaseModel):
    id: UUID
    organization_id: UUID
    vendor_id: UUID
    run_id: UUID | None
    storage_path: str
    original_filename: str
    content_type: str
    byte_size: int
    sha256: str
    source: DocSource
    version_number: int
    supersedes_document_id: UUID | None
    status: DocStatus
    valid_from: date | None
    valid_to: date | None
    is_current: bool
    received_at: datetime


class CoiExtractionRow(BaseModel):
    id: UUID
    organization_id: UUID
    run_id: UUID | None
    coi_document_id: UUID
    extracted: dict[str, Any]
    field_confidence: dict[str, Any]
    overall_confidence: float
    model: str
    prompt_hash: str
    input_tokens: int
    output_tokens: int
    cost_cents: int
    is_current: bool
    created_at: datetime


class CoiValidationRow(BaseModel):
    id: UUID
    organization_id: UUID
    run_id: UUID | None
    coi_extraction_id: UUID
    result: ValidationResult
    line_results: list[dict[str, Any]]
    flags: list[dict[str, Any]]
    faithfulness_ok: bool
    created_at: datetime


class EscalationRow(BaseModel):
    id: UUID
    organization_id: UUID
    run_id: UUID
    vendor_id: UUID
    kind: EscalationKind
    reason_code: str
    severity: EventSeverity
    summary: str
    details: dict[str, Any]
    status: EscalationStatus
    resolution: str | None
    created_at: datetime
    resolved_at: datetime | None


class EmailMessageRow(BaseModel):
    id: UUID
    organization_id: UUID
    run_id: UUID | None
    vendor_id: UUID | None
    direction: EmailDirection
    provider_message_id: str | None
    reply_token: str | None
    subject: str
    body_snapshot: str
    to_email: str
    from_email: str
    status: str
    attachments_count: int
    created_at: datetime
