"""
Mirrors ADR 0005 (`RequirementsRetriever` interface) verbatim. This is the
literal contract backend/agent-engineer implement against — field names and
types must match exactly so `harness/retriever_adapter.py` can call a real
`V1DeterministicRetriever` without any translation layer.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol
from uuid import UUID

from pydantic import BaseModel

from tests.evals.contracts.validation import CoverageType, PropertyType, VendorRole


class RequirementsQuery(BaseModel):
    organization_id: UUID
    jurisdiction_state: str
    jurisdiction_city: Optional[str] = None
    jurisdiction_hoa: Optional[str] = None
    property_type: Optional[PropertyType] = None
    vendor_role: VendorRole


class RetrievedRequirement(BaseModel):
    id: UUID  # compliance_requirements.id — the faithfulness anchor
    coverage_type: CoverageType
    min_each_occurrence: Optional[int] = None
    min_aggregate: Optional[int] = None
    requires_additional_insured: bool
    requires_waiver_of_subrogation: bool
    requires_primary_noncontributory: bool
    source_citation: str
    source_url: Optional[str] = None
    last_verified_at: datetime


class RetrievalResult(BaseModel):
    requirements: list[RetrievedRequirement]
    found: bool  # False -> fallback fires (never []->proceed)
    query: RequirementsQuery


class RequirementsRetriever(Protocol):
    def retrieve(self, q: RequirementsQuery) -> RetrievalResult: ...
