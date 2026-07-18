"""RequirementsRetriever interface + v1 deterministic implementation
(ADR 0005). Orchestration depends only on the `RequirementsRetriever`
Protocol; `V1DeterministicRetriever` is the only implementation in v1.

# ASSUMPTION: semantic RAG deferred until the curation workflow exists; v1
knowledge is human-curated rows (CLAUDE.md retrieval section). A future
`V2SemanticRetriever` implements the same Protocol and MUST still resolve to
persisted, cited `compliance_requirements` rows — it never returns
un-curated free-text requirements (ADR 0005 v2 seam).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

import asyncpg
from pydantic import BaseModel

from app.models.enums import CoverageType, PropertyType, VendorRole


class RequirementsQuery(BaseModel):
    organization_id: UUID
    jurisdiction_state: str
    jurisdiction_city: str | None
    jurisdiction_hoa: str | None
    property_type: PropertyType | None
    vendor_role: VendorRole


class RetrievedRequirement(BaseModel):
    id: UUID  # compliance_requirements.id — the faithfulness anchor
    coverage_type: CoverageType
    min_each_occurrence: int | None
    min_aggregate: int | None
    requires_additional_insured: bool
    requires_waiver_of_subrogation: bool
    requires_primary_noncontributory: bool
    source_citation: str
    source_url: str | None
    last_verified_at: datetime


class RetrievalResult(BaseModel):
    requirements: list[RetrievedRequirement]
    found: bool  # False -> fallback fires (never []->proceed)
    query: RequirementsQuery


class RequirementsRetriever(Protocol):
    async def retrieve(self, q: RequirementsQuery) -> RetrievalResult: ...


class V1DeterministicRetriever:
    """Predicate match with jurisdiction-specificity ranking (ADR 0005).
    Most-specific KB row wins per coverage_type; NULL in a KB column means
    "applies to any". Reduces to one row per coverage_type.
    """

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    async def retrieve(self, q: RequirementsQuery) -> RetrievalResult:
        rows = await self._conn.fetch(
            """
            select id, coverage_type, min_each_occurrence, min_aggregate,
                   requires_additional_insured, requires_waiver_of_subrogation,
                   requires_primary_noncontributory, source_citation, source_url,
                   last_verified_at,
                   (jurisdiction_city is not null)::int
                     + (jurisdiction_hoa is not null)::int
                     + (property_type is not null)::int
                     + (vendor_role is not null)::int as specificity
            from compliance_requirements
            where organization_id = $1 and active
              and jurisdiction_state = $2
              and (jurisdiction_city is null or jurisdiction_city = $3)
              and (jurisdiction_hoa  is null or jurisdiction_hoa  = $4)
              and (property_type     is null or property_type     = $5)
              and (vendor_role       is null or vendor_role       = $6)
            order by coverage_type, specificity desc
            """,
            q.organization_id,
            q.jurisdiction_state,
            q.jurisdiction_city,
            q.jurisdiction_hoa,
            q.property_type.value if q.property_type else None,
            q.vendor_role.value,
        )

        # Reduce to one row per coverage_type (first row per group is the
        # most specific, thanks to `order by coverage_type, specificity desc`).
        best_by_coverage: dict[str, asyncpg.Record] = {}
        for r in rows:
            key = r["coverage_type"]
            if key not in best_by_coverage:
                best_by_coverage[key] = r

        requirements = [
            RetrievedRequirement(
                id=r["id"],
                coverage_type=r["coverage_type"],
                min_each_occurrence=r["min_each_occurrence"],
                min_aggregate=r["min_aggregate"],
                requires_additional_insured=r["requires_additional_insured"],
                requires_waiver_of_subrogation=r["requires_waiver_of_subrogation"],
                requires_primary_noncontributory=r["requires_primary_noncontributory"],
                source_citation=r["source_citation"],
                source_url=r["source_url"],
                last_verified_at=r["last_verified_at"],
            )
            for r in best_by_coverage.values()
        ]

        return RetrievalResult(
            requirements=requirements,
            found=len(requirements) > 0,
            query=q,
        )
