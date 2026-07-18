"""
Mirrors the `compliance_requirements` / `vendor_coverage_requirements` /
`coi_validations` shapes from ADR 0001, plus the closed enums those rows use.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CoverageType(str, Enum):
    GENERAL_LIABILITY = "general_liability"
    AUTO_LIABILITY = "auto_liability"
    WORKERS_COMP = "workers_comp"
    UMBRELLA_EXCESS = "umbrella_excess"
    PROFESSIONAL_LIABILITY = "professional_liability"
    POLLUTION = "pollution"
    EMPLOYERS_LIABILITY = "employers_liability"


class VendorRole(str, Enum):
    PLUMBER = "plumber"
    ELECTRICIAN = "electrician"
    HVAC = "hvac"
    GENERAL_CONTRACTOR = "general_contractor"
    LANDSCAPER = "landscaper"
    ROOFER = "roofer"
    CLEANER = "cleaner"
    PEST_CONTROL = "pest_control"
    OTHER = "other"


class PropertyType(str, Enum):
    SINGLE_FAMILY = "single_family"
    MULTI_FAMILY = "multi_family"
    CONDO = "condo"
    COMMERCIAL = "commercial"
    MIXED_USE = "mixed_use"


class ValidationResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class LineResult(BaseModel):
    """One row of `coi_validations.line_results`. This is the faithfulness
    anchor structure: every asserted requirement must carry BOTH ids."""

    vendor_coverage_requirement_id: UUID
    source_compliance_requirement_id: Optional[UUID]  # None = unverified override (ADR 0001)
    coverage_type: CoverageType
    parsed_value: Any
    required_value: Any
    passed: bool
    severity: str = "info"  # info|warn|error


class CoiValidation(BaseModel):
    """Mirrors `coi_validations`. `result` and `faithfulness_ok` are computed
    deterministically in code — never by LLM judgment (ADR 0002/0004)."""

    result: ValidationResult
    line_results: list[LineResult]
    flags: list[str] = Field(default_factory=list)  # e.g. "policy_expired", "no_requirements_on_file"
    faithfulness_ok: bool


class VendorCoverageRequirementFixture(BaseModel):
    """Mirrors one row of `vendor_coverage_requirements` for fixture seeding."""

    coverage_type: CoverageType
    min_each_occurrence: Optional[int] = None
    min_aggregate: Optional[int] = None
    requires_additional_insured: bool = False
    requires_waiver_of_subrogation: bool = False
    requires_primary_noncontributory: bool = False
    source_compliance_requirement_id: Optional[UUID] = None  # None -> unverified override
