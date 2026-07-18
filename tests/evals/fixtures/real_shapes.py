"""
Converters from this harness's fixture shapes (GoldenDocumentFixture's flat
`expected_extraction` dict + `VendorCoverageRequirementFixture` list) into
the REAL pydantic types `app.tools.validation_logic.evaluate_validation`
takes, so test_validation_logic.py can call real backend code directly with
fixture data instead of needing a live DB or a full pipeline.

Import of the real `app.*` types is deferred into each function (not at
module load time) so this file — and everything that imports it, including
fixtures/golden_manifest.py indirectly via test collection — stays importable
even when backend/ isn't on sys.path yet (harness/validation_adapter.py is
what actually puts it there, and only when a test asks for it).
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING
from uuid import UUID

from tests.evals.contracts.validation import VendorCoverageRequirementFixture
from tests.evals.fixtures.ids import stable_id

if TYPE_CHECKING:
    from app.models.coi_fields import ExtractedCoiFields
    from app.retrieval.models import VendorCoverageRequirementRow


def to_extracted_coi_fields(fixture_id: str, flat: dict[str, Any]) -> "ExtractedCoiFields":
    from app.models.coi_fields import ExtractedCoiFields, ExtractedCoverageLine
    from app.models.enums import CoverageType

    # Discover which coverage types are present by scanning for
    # "coverage.<type>.<field>" keys — keeps this converter fixture-agnostic
    # rather than hardcoding the coverage lines every fixture happens to use.
    coverage_types_present: set[str] = set()
    for key in flat:
        if key.startswith("coverage."):
            coverage_types_present.add(key.split(".")[1])

    coverage_lines = []
    for ct in coverage_types_present:
        prefix = f"coverage.{ct}."
        coverage_lines.append(
            ExtractedCoverageLine(
                coverage_type=CoverageType(ct),
                each_occurrence=flat.get(prefix + "each_occurrence"),
                aggregate=flat.get(prefix + "aggregate"),
                additional_insured=flat.get(prefix + "additional_insured"),
                waiver_of_subrogation=flat.get(prefix + "waiver_of_subrogation"),
                primary_noncontributory=flat.get(prefix + "primary_noncontributory"),
                # ASSUMPTION: golden fixtures don't model per-line confidence
                # (that's an agent-engineer extraction-quality concern, not a
                # deterministic-validation one) — every fixture line is
                # authored as high-confidence (1.0) so validation_logic's
                # confidence gate never fires for extraction fixtures whose
                # point is testing coverage-limit/date/faithfulness logic,
                # not confidence thresholds (garbage_01/02 test confidence
                # separately and are excluded from this converter entirely).
                confidence=1.0,
            )
        )

    return ExtractedCoiFields(
        insured_name_on_certificate=flat.get("insured_name"),
        policy_effective_date=flat.get("policy.valid_from"),
        policy_expiration_date=flat.get("policy.valid_to"),
        coverage_lines=coverage_lines,
        overall_confidence=1.0,
    )


def to_vendor_coverage_requirement_rows(
    fixture_id: str,
    organization_id: UUID,
    vendor_id: UUID,
    requirements: list[VendorCoverageRequirementFixture],
) -> list["VendorCoverageRequirementRow"]:
    from app.retrieval.models import VendorCoverageRequirementRow

    return [
        VendorCoverageRequirementRow(
            id=stable_id(f"vcr:{fixture_id}:{req.coverage_type.value}"),
            organization_id=organization_id,
            vendor_id=vendor_id,
            coverage_type=req.coverage_type,
            min_each_occurrence=req.min_each_occurrence,
            min_aggregate=req.min_aggregate,
            requires_additional_insured=req.requires_additional_insured,
            requires_waiver_of_subrogation=req.requires_waiver_of_subrogation,
            requires_primary_noncontributory=req.requires_primary_noncontributory,
            source_compliance_requirement_id=req.source_compliance_requirement_id,
            confirmed_by_pm=True,
        )
        for req in requirements
    ]


def active_kb_ids_for(requirements: list[VendorCoverageRequirementFixture]) -> set[UUID]:
    """Every KB row referenced by a fixture's requirements is 'active' by
    construction in this harness's fixture world (fixtures don't model a
    deactivated-after-materialization KB row — that's a narrower scenario
    than the golden set currently covers). A None source id is correctly
    excluded here: real code treats None as unbacked regardless of this set."""
    return {req.source_compliance_requirement_id for req in requirements if req.source_compliance_requirement_id}
