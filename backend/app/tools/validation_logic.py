"""Deterministic COI validation (all-or-nothing, per CLAUDE.md's locked
product decision). Pure function — no DB, no LLM — so it is directly
unit-testable against fixtures (qa-evals-engineer's golden-document harness
hangs off this). The LLM never decides pass/fail; this is it.

Faithfulness (ADR 0005, structural "IDs in, IDs out"):
  - IDs in: every `VendorCoverageRequirementRow` used here already carries
    `source_compliance_requirement_id` (materialized at onboarding from the
    retriever).
  - IDs out: every `line_results` entry emitted here carries both
    `vendor_coverage_requirement_id` and `source_compliance_requirement_id`.
  - Faithfulness fails structurally (not by trusting the LLM) whenever a
    required line has no `source_compliance_requirement_id`, or that id
    doesn't resolve to an ACTIVE `compliance_requirements` row passed in via
    `active_kb_ids` — i.e. the KB row was deactivated after the vendor's
    requirement set was materialized.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from app.models.coi_fields import ExtractedCoiFields, ExtractedCoverageLine
from app.retrieval.models import VendorCoverageRequirementRow


@dataclass
class ValidationOutcome:
    result: str  # 'pass' | 'fail'
    line_results: list[dict[str, Any]] = field(default_factory=list)
    flags: list[dict[str, Any]] = field(default_factory=list)
    faithfulness_ok: bool = True
    no_requirements_on_file: bool = False


def _line_for(coverage_type: str, lines: list[ExtractedCoverageLine]) -> ExtractedCoverageLine | None:
    for line in lines:
        if line.coverage_type.value == coverage_type:
            return line
    return None


def evaluate_validation(
    *,
    requirements: list[VendorCoverageRequirementRow],
    extraction: ExtractedCoiFields,
    active_kb_ids: set[UUID],
    confidence_threshold: float,
    as_of: date | None = None,
) -> ValidationOutcome:
    as_of = as_of or date.today()

    if not requirements:
        return ValidationOutcome(
            result="fail",
            faithfulness_ok=False,
            no_requirements_on_file=True,
            flags=[
                {
                    "code": "no_requirements_on_file",
                    "severity": "high",
                    "message": "Vendor has no vendor_coverage_requirements on file.",
                }
            ],
        )

    line_results: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []
    overall_pass = True
    faithfulness_ok = True
    no_requirements_on_file = False

    # Document-level staleness: an expired policy fails every line, but we
    # still evaluate line-by-line so the human reviewer sees full detail.
    is_expired = extraction.policy_expiration_date is not None and extraction.policy_expiration_date < as_of
    if extraction.policy_expiration_date is None:
        flags.append(
            {
                "code": "missing_expiration_date",
                "severity": "high",
                "message": "Extraction did not report a policy expiration date.",
            }
        )
        overall_pass = False
    elif is_expired:
        flags.append(
            {
                "code": "policy_expired",
                "severity": "high",
                "message": f"Policy expiration {extraction.policy_expiration_date} is before {as_of}.",
            }
        )
        overall_pass = False

    # Not-yet-effective: a policy that hasn't started yet provides no
    # coverage as of `as_of`, and must fail just like an expired one.
    # Regression test: tests/test_validation_logic.py::TestNotYetEffective
    # (caught by qa-evals-engineer against this exact function).
    if extraction.policy_effective_date is not None and extraction.policy_effective_date > as_of:
        flags.append(
            {
                "code": "policy_not_yet_effective",
                "severity": "high",
                "message": f"Policy effective date {extraction.policy_effective_date} is after {as_of}.",
            }
        )
        overall_pass = False

    if extraction.overall_confidence < confidence_threshold:
        flags.append(
            {
                "code": "low_confidence_extraction",
                "severity": "high",
                "message": f"overall_confidence {extraction.overall_confidence} < threshold {confidence_threshold}.",
            }
        )
        overall_pass = False

    for req in requirements:
        # --- Faithfulness (structural, IDs in / IDs out) ---
        backed = req.source_compliance_requirement_id is not None and (
            req.source_compliance_requirement_id in active_kb_ids
        )
        if not backed:
            faithfulness_ok = False
            flags.append(
                {
                    "code": "unverified_requirement",
                    "severity": "high",
                    "coverage_type": req.coverage_type.value,
                    "message": "Required line has no backing active compliance_requirements row.",
                }
            )

        line = _line_for(req.coverage_type.value, extraction.coverage_lines)
        line_pass = True
        reasons: list[str] = []

        if line is None:
            line_pass = False
            reasons.append("missing_coverage_line")
        else:
            if line.confidence < confidence_threshold:
                line_pass = False
                reasons.append("low_confidence_line")
            if req.min_each_occurrence is not None:
                if line.each_occurrence is None or line.each_occurrence < req.min_each_occurrence:
                    line_pass = False
                    reasons.append("each_occurrence_below_minimum")
            if req.min_aggregate is not None:
                if line.aggregate is None or line.aggregate < req.min_aggregate:
                    line_pass = False
                    reasons.append("aggregate_below_minimum")
            if req.requires_additional_insured and not line.additional_insured:
                line_pass = False
                reasons.append("missing_additional_insured")
            if req.requires_waiver_of_subrogation and not line.waiver_of_subrogation:
                line_pass = False
                reasons.append("missing_waiver_of_subrogation")
            if req.requires_primary_noncontributory and not line.primary_noncontributory:
                line_pass = False
                reasons.append("missing_primary_noncontributory")

        if not line_pass:
            overall_pass = False

        line_results.append(
            {
                "vendor_coverage_requirement_id": str(req.id),
                "source_compliance_requirement_id": (
                    str(req.source_compliance_requirement_id)
                    if req.source_compliance_requirement_id
                    else None
                ),
                "coverage_type": req.coverage_type.value,
                "required": {
                    "min_each_occurrence": req.min_each_occurrence,
                    "min_aggregate": req.min_aggregate,
                    "requires_additional_insured": req.requires_additional_insured,
                    "requires_waiver_of_subrogation": req.requires_waiver_of_subrogation,
                    "requires_primary_noncontributory": req.requires_primary_noncontributory,
                },
                "parsed": (
                    {
                        "each_occurrence": line.each_occurrence,
                        "aggregate": line.aggregate,
                        "additional_insured": line.additional_insured,
                        "waiver_of_subrogation": line.waiver_of_subrogation,
                        "primary_noncontributory": line.primary_noncontributory,
                        "confidence": line.confidence,
                    }
                    if line is not None
                    else None
                ),
                "pass": line_pass,
                "severity": "high" if not line_pass else "info",
                "reasons": reasons,
            }
        )

    # All-or-nothing (CLAUDE.md locked decision): any failing line fails
    # the whole validation, never partially filed.
    result = "pass" if (overall_pass and faithfulness_ok) else "fail"

    return ValidationOutcome(
        result=result,
        line_results=line_results,
        flags=flags,
        faithfulness_ok=faithfulness_ok,
        no_requirements_on_file=no_requirements_on_file,
    )
