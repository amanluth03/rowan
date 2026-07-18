"""Tests for the deterministic COI validation comparison (app/tools/
validation_logic.py) — the "yours to implement" pass/fail logic. Pure
function, no DB, no LLM: exactly what CLAUDE.md's all-or-nothing locked
decision needs covered before anything else touches it.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4


from app.models.coi_fields import ExtractedCoiFields, ExtractedCoverageLine
from app.models.enums import CoverageType
from app.retrieval.models import VendorCoverageRequirementRow
from app.tools.validation_logic import evaluate_validation

ORG_ID = uuid4()
VENDOR_ID = uuid4()


def _requirement(
    coverage_type: CoverageType,
    *,
    min_each_occurrence: int | None = 1_000_000,
    min_aggregate: int | None = 2_000_000,
    requires_additional_insured: bool = True,
    requires_waiver_of_subrogation: bool = False,
    requires_primary_noncontributory: bool = False,
    source_compliance_requirement_id=None,
) -> VendorCoverageRequirementRow:
    return VendorCoverageRequirementRow(
        id=uuid4(),
        organization_id=ORG_ID,
        vendor_id=VENDOR_ID,
        coverage_type=coverage_type,
        min_each_occurrence=min_each_occurrence,
        min_aggregate=min_aggregate,
        requires_additional_insured=requires_additional_insured,
        requires_waiver_of_subrogation=requires_waiver_of_subrogation,
        requires_primary_noncontributory=requires_primary_noncontributory,
        source_compliance_requirement_id=source_compliance_requirement_id or uuid4(),
        confirmed_by_pm=True,
    )


def _clean_extraction(**overrides) -> ExtractedCoiFields:
    defaults = dict(
        insured_name_on_certificate="Hernandez Plumbing",
        policy_effective_date=date(2026, 1, 1),
        policy_expiration_date=date(2027, 1, 1),
        coverage_lines=[
            ExtractedCoverageLine(
                coverage_type=CoverageType.general_liability,
                each_occurrence=1_000_000,
                aggregate=2_000_000,
                additional_insured=True,
                waiver_of_subrogation=True,
                primary_noncontributory=True,
                confidence=0.95,
            )
        ],
        overall_confidence=0.95,
    )
    defaults.update(overrides)
    return ExtractedCoiFields(**defaults)


class TestNoRequirementsFallback:
    def test_empty_requirements_fails_and_flags_no_requirements_on_file(self):
        result = evaluate_validation(
            requirements=[],
            extraction=_clean_extraction(),
            active_kb_ids=set(),
            confidence_threshold=0.80,
            as_of=date(2026, 6, 1),
        )
        assert result.result == "fail"
        assert result.no_requirements_on_file is True
        assert result.faithfulness_ok is False
        assert any(f["code"] == "no_requirements_on_file" for f in result.flags)


class TestCleanRenewal:
    def test_clean_renewal_passes(self):
        req = _requirement(CoverageType.general_liability)
        result = evaluate_validation(
            requirements=[req],
            extraction=_clean_extraction(),
            active_kb_ids={req.source_compliance_requirement_id},
            confidence_threshold=0.80,
            as_of=date(2026, 6, 1),
        )
        assert result.result == "pass"
        assert result.faithfulness_ok is True
        assert len(result.line_results) == 1
        assert result.line_results[0]["pass"] is True
        assert result.line_results[0]["vendor_coverage_requirement_id"] == str(req.id)
        assert result.line_results[0]["source_compliance_requirement_id"] == str(
            req.source_compliance_requirement_id
        )


class TestLowLimits:
    def test_each_occurrence_below_minimum_fails_whole_validation(self):
        req = _requirement(CoverageType.general_liability, min_each_occurrence=1_000_000)
        extraction = _clean_extraction(
            coverage_lines=[
                ExtractedCoverageLine(
                    coverage_type=CoverageType.general_liability,
                    each_occurrence=500_000,  # below minimum
                    aggregate=2_000_000,
                    additional_insured=True,
                    confidence=0.95,
                )
            ]
        )
        result = evaluate_validation(
            requirements=[req],
            extraction=extraction,
            active_kb_ids={req.source_compliance_requirement_id},
            confidence_threshold=0.80,
            as_of=date(2026, 6, 1),
        )
        assert result.result == "fail"
        assert "each_occurrence_below_minimum" in result.line_results[0]["reasons"]


class TestMissingAdditionalInsured:
    def test_missing_additional_insured_fails(self):
        req = _requirement(CoverageType.general_liability, requires_additional_insured=True)
        extraction = _clean_extraction(
            coverage_lines=[
                ExtractedCoverageLine(
                    coverage_type=CoverageType.general_liability,
                    each_occurrence=1_000_000,
                    aggregate=2_000_000,
                    additional_insured=False,
                    confidence=0.95,
                )
            ]
        )
        result = evaluate_validation(
            requirements=[req],
            extraction=extraction,
            active_kb_ids={req.source_compliance_requirement_id},
            confidence_threshold=0.80,
            as_of=date(2026, 6, 1),
        )
        assert result.result == "fail"
        assert "missing_additional_insured" in result.line_results[0]["reasons"]


class TestWrongOrMissingDates:
    def test_expired_policy_fails(self):
        req = _requirement(CoverageType.general_liability)
        extraction = _clean_extraction(policy_expiration_date=date(2026, 1, 1))
        result = evaluate_validation(
            requirements=[req],
            extraction=extraction,
            active_kb_ids={req.source_compliance_requirement_id},
            confidence_threshold=0.80,
            as_of=date(2026, 6, 1),  # after expiration
        )
        assert result.result == "fail"
        assert any(f["code"] == "policy_expired" for f in result.flags)

    def test_missing_expiration_date_fails(self):
        req = _requirement(CoverageType.general_liability)
        extraction = _clean_extraction(policy_expiration_date=None)
        result = evaluate_validation(
            requirements=[req],
            extraction=extraction,
            active_kb_ids={req.source_compliance_requirement_id},
            confidence_threshold=0.80,
        )
        assert result.result == "fail"
        assert any(f["code"] == "missing_expiration_date" for f in result.flags)


class TestMissingCoverageLine:
    def test_all_or_nothing_partial_coverage_still_fails_whole_validation(self):
        """CLAUDE.md locked decision: a COI is validated as one unit against
        every required line. Any missing line fails the WHOLE validation."""
        gl_req = _requirement(CoverageType.general_liability)
        wc_req = _requirement(CoverageType.workers_comp, min_each_occurrence=None, min_aggregate=None)
        extraction = _clean_extraction()  # only has general_liability line

        result = evaluate_validation(
            requirements=[gl_req, wc_req],
            extraction=extraction,
            active_kb_ids={gl_req.source_compliance_requirement_id, wc_req.source_compliance_requirement_id},
            confidence_threshold=0.80,
            as_of=date(2026, 6, 1),
        )
        assert result.result == "fail"
        wc_line = next(lr for lr in result.line_results if lr["coverage_type"] == "workers_comp")
        assert wc_line["pass"] is False
        assert "missing_coverage_line" in wc_line["reasons"]
        # the passing GL line does not rescue the overall result
        gl_line = next(lr for lr in result.line_results if lr["coverage_type"] == "general_liability")
        assert gl_line["pass"] is True
        assert result.result == "fail"


class TestLowConfidence:
    def test_low_overall_confidence_fails(self):
        req = _requirement(CoverageType.general_liability)
        extraction = _clean_extraction(overall_confidence=0.5)
        result = evaluate_validation(
            requirements=[req],
            extraction=extraction,
            active_kb_ids={req.source_compliance_requirement_id},
            confidence_threshold=0.80,
            as_of=date(2026, 6, 1),
        )
        assert result.result == "fail"
        assert any(f["code"] == "low_confidence_extraction" for f in result.flags)

    def test_low_line_confidence_fails_that_line(self):
        req = _requirement(CoverageType.general_liability)
        extraction = _clean_extraction(
            coverage_lines=[
                ExtractedCoverageLine(
                    coverage_type=CoverageType.general_liability,
                    each_occurrence=1_000_000,
                    aggregate=2_000_000,
                    additional_insured=True,
                    confidence=0.4,  # low
                )
            ]
        )
        result = evaluate_validation(
            requirements=[req],
            extraction=extraction,
            active_kb_ids={req.source_compliance_requirement_id},
            confidence_threshold=0.80,
            as_of=date(2026, 6, 1),
        )
        assert result.result == "fail"
        assert "low_confidence_line" in result.line_results[0]["reasons"]


class TestFaithfulness:
    def test_unbacked_requirement_forces_needs_human_review_via_faithfulness_flag(self):
        """A vendor_coverage_requirement with no active KB row backing it
        must never silently validate — ADR 0005 structural faithfulness."""
        req = _requirement(CoverageType.general_liability, source_compliance_requirement_id=uuid4())
        result = evaluate_validation(
            requirements=[req],
            extraction=_clean_extraction(),
            active_kb_ids=set(),  # req's KB id NOT in the active set
            confidence_threshold=0.80,
            as_of=date(2026, 6, 1),
        )
        assert result.faithfulness_ok is False
        assert result.result == "fail"
        assert any(f["code"] == "unverified_requirement" for f in result.flags)

    def test_null_source_compliance_requirement_id_is_unverified(self):
        req = _requirement(CoverageType.general_liability)
        req = req.model_copy(update={"source_compliance_requirement_id": None})
        result = evaluate_validation(
            requirements=[req],
            extraction=_clean_extraction(),
            active_kb_ids=set(),
            confidence_threshold=0.80,
            as_of=date(2026, 6, 1),
        )
        assert result.faithfulness_ok is False


class TestIdsOut:
    def test_every_line_result_carries_both_ids(self):
        req = _requirement(CoverageType.general_liability)
        result = evaluate_validation(
            requirements=[req],
            extraction=_clean_extraction(),
            active_kb_ids={req.source_compliance_requirement_id},
            confidence_threshold=0.80,
            as_of=date(2026, 6, 1),
        )
        for lr in result.line_results:
            assert lr["vendor_coverage_requirement_id"]
            assert lr["source_compliance_requirement_id"]


class TestNotYetEffective:
    """Regression test for a bug qa-evals-engineer caught: a COI whose
    policy_effective_date is in the future (not yet effective) must fail,
    not silently pass. Mirrors their `future_dated_02_pestaway` fixture."""

    def test_future_effective_date_fails(self):
        req = _requirement(CoverageType.general_liability)
        extraction = _clean_extraction(
            policy_effective_date=date(2026, 12, 1),  # starts in the future
            policy_expiration_date=date(2027, 12, 1),
        )
        result = evaluate_validation(
            requirements=[req],
            extraction=extraction,
            active_kb_ids={req.source_compliance_requirement_id},
            confidence_threshold=0.80,
            as_of=date(2026, 6, 1),  # today is before effective date
        )
        assert result.result == "fail"
        assert any(f["code"] == "policy_not_yet_effective" for f in result.flags)
