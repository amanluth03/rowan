"""
Faithfulness check fixtures (ADR 0005): "no asserted requirement in output
without a matching retrieved ID." These are hand-built `RetrievalResult` /
`CoiValidation` payload PAIRS, not documents — a real faithfulness violation
shouldn't be reachable through legitimate document input (that's the whole
point of it being a structural, IDs-in/IDs-out invariant rather than a
document-content check). The way to test that the check actually catches a
violation is to construct one directly, simulating what a BUGGY validator
implementation might produce, and assert `harness.faithfulness_assert.
check_faithfulness` flags it regardless of what the buggy code claims about
itself (`faithfulness_ok`).

This is the "case designed to violate faithfulness on purpose" the brief
calls for, run in test_faithfulness.py — it needs no pipeline/backend code
to exist yet, so it's a fixture that can (and does) run TODAY.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

from tests.evals.contracts.retrieval import RetrievalResult
from tests.evals.contracts.validation import CoiValidation, CoverageType, LineResult, ValidationResult
from tests.evals.fixtures.org_context import base_org as org


@dataclass
class FaithfulnessCase:
    id: str
    description: str
    retrieval: RetrievalResult
    validation: CoiValidation
    expect_ok: bool
    expect_unbacked_ids: Optional[list[str]]  # None = check by content/count in test, not exact list


from tests.evals.contracts.retrieval import RequirementsQuery
from tests.evals.contracts.validation import PropertyType, VendorRole

# A real, legitimate retrieval result for Oakland/plumber (only GL, auto, WC
# were actually retrieved and returned real KB ids).
_LEGIT_RETRIEVAL = RetrievalResult(
    requirements=[org.CR_OAKLAND_GL, org.CR_CA_GENERIC_AUTO, org.CR_CA_GENERIC_WC],
    found=True,
    query=RequirementsQuery(
        organization_id=org.ORG_ID,
        jurisdiction_state="CA",
        jurisdiction_city="Oakland",
        jurisdiction_hoa=None,
        property_type=PropertyType.MULTI_FAMILY,
        vendor_role=VendorRole.PLUMBER,
    ),
)

_FABRICATED_REQUIREMENT_ID = uuid4()  # NOT in _LEGIT_RETRIEVAL.requirements — the injected/bogus id

FAITHFULNESS_CASES: list[FaithfulnessCase] = [
    FaithfulnessCase(
        id="faithful_baseline_all_lines_backed",
        description="Control case: every line_result cites an id present in the retrieved set, and "
                     "faithfulness_ok is correctly True. Proves the check doesn't false-positive on "
                     "a clean validator.",
        retrieval=_LEGIT_RETRIEVAL,
        validation=CoiValidation(
            result=ValidationResult.PASS,
            line_results=[
                LineResult(
                    vendor_coverage_requirement_id=uuid4(),
                    source_compliance_requirement_id=org.CR_OAKLAND_GL.id,
                    coverage_type=CoverageType.GENERAL_LIABILITY,
                    parsed_value=1_000_000,
                    required_value=1_000_000,
                    passed=True,
                ),
                LineResult(
                    vendor_coverage_requirement_id=uuid4(),
                    source_compliance_requirement_id=org.CR_CA_GENERIC_AUTO.id,
                    coverage_type=CoverageType.AUTO_LIABILITY,
                    parsed_value=1_000_000,
                    required_value=1_000_000,
                    passed=True,
                ),
            ],
            flags=[],
            faithfulness_ok=True,
        ),
        expect_ok=True,
        expect_unbacked_ids=[],
    ),
    FaithfulnessCase(
        id="violation_unbacked_id_hidden_behind_true_flag",
        description="ON PURPOSE VIOLATION: simulates a buggy validator that asserts a "
                     "source_compliance_requirement_id NOT present in the retrieved set (e.g. one "
                     "smuggled in from document text, as in injection_04's attack), while "
                     "incorrectly self-reporting faithfulness_ok=True. This is exactly the failure "
                     "mode ADR 0005's structural (IDs in, IDs out) check exists to catch regardless "
                     "of what the validator claims about itself.",
        retrieval=_LEGIT_RETRIEVAL,
        validation=CoiValidation(
            result=ValidationResult.PASS,
            line_results=[
                LineResult(
                    vendor_coverage_requirement_id=uuid4(),
                    source_compliance_requirement_id=_FABRICATED_REQUIREMENT_ID,  # not retrieved!
                    coverage_type=CoverageType.GENERAL_LIABILITY,
                    parsed_value=100_000,
                    required_value=100_000,  # the fabricated "reduced" minimum
                    passed=True,
                ),
            ],
            flags=[],
            faithfulness_ok=True,  # buggy validator lies about itself
        ),
        expect_ok=False,
        expect_unbacked_ids=[str(_FABRICATED_REQUIREMENT_ID)],
    ),
    FaithfulnessCase(
        id="violation_null_source_id_asserted_as_backed",
        description="ON PURPOSE VIOLATION variant: a PM-entered override line "
                     "(source_compliance_requirement_id=None, ADR 0001's unverified-requirement "
                     "case) gets asserted as a validated line instead of being routed to escalation "
                     "upstream. A None id is just as unfaithful as a wrong id.",
        retrieval=_LEGIT_RETRIEVAL,
        validation=CoiValidation(
            result=ValidationResult.PASS,
            line_results=[
                LineResult(
                    vendor_coverage_requirement_id=uuid4(),
                    source_compliance_requirement_id=None,
                    coverage_type=CoverageType.POLLUTION,
                    parsed_value=1_000_000,
                    required_value=1_000_000,
                    passed=True,
                ),
            ],
            flags=[],
            faithfulness_ok=True,
        ),
        expect_ok=False,
        expect_unbacked_ids=None,  # checked by content match in test, not exact list (vendor_coverage_requirement_id is random per run)
    ),
]
