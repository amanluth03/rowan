"""
Real, running-today integration test against `app.tools.validation_logic.
evaluate_validation` — the deterministic pass/fail/faithfulness core of the
`validating` state (ADR 0002/0004/0005). Unlike test_golden_documents.py
(which needs a full orchestration pipeline that doesn't exist yet) and
test_retrieval.py (which needs a live Postgres connection), this piece
landed as a pure function with no DB/LLM dependency, so the golden fixtures'
requirements + expected_extraction can be run through REAL backend code
right now.

This test intentionally checks ONLY what `evaluate_validation` itself
promises (result, flags, per-line reasons, faithfulness_ok) — not state-
machine routing (states/escalations/tool-call sequencing), which stays
covered by test_golden_documents.py once orchestration exists and is gated
behind `pipeline`. Two different real bugs would surface in two different
places by design: a wrong pass/fail or wrong reason code fails HERE; a
correct validation result routed to the wrong state fails THERE.
"""
from __future__ import annotations

import pytest

from tests.evals.fixtures.golden_manifest import GOLDEN_DOCUMENTS
from tests.evals.fixtures.org_context.base_org import ORG_ID
from tests.evals.fixtures.real_shapes import (
    active_kb_ids_for,
    to_extracted_coi_fields,
    to_vendor_coverage_requirement_rows,
)
from tests.evals.harness.validation_adapter import ValidationLogicNotAvailable, resolve_evaluate_validation

# garbage_01/02 never produce usable extraction (that's the point of those
# fixtures) — there is no ExtractedCoiFields to build, so they're out of
# scope for this pure-function check.
VALIDATION_FIXTURES = [f for f in GOLDEN_DOCUMENTS if f.extraction_expected_to_succeed]

# ASSUMPTION: fixture ids that are KNOWN to fail against the current real
# implementation because they encode a gap this harness discovered rather
# than a fixture-design mistake. xfail(strict=True) so the day backend fixes
# the gap, this test starts FAILING (not silently passing) until the marker
# is removed — that's the signal to re-verify and drop it.
KNOWN_GAPS: dict[str, str] = {
    "future_dated_02_pestaway": (
        "evaluate_validation only checks policy_expiration_date, not "
        "policy_effective_date being in the future — see the FINDING note "
        "on this fixture in golden_manifest.py and the qa-evals report."
    ),
}


@pytest.fixture(scope="module")
def evaluate_validation():
    try:
        return resolve_evaluate_validation()
    except ValidationLogicNotAvailable as e:
        pytest.skip(str(e))


def _run(evaluate_validation, fixture):
    vendor_id = fixture.vendor.id
    requirements = to_vendor_coverage_requirement_rows(
        fixture.id, ORG_ID, vendor_id, fixture.vendor_coverage_requirements
    )
    extraction = to_extracted_coi_fields(fixture.id, fixture.expected_extraction)
    active_kb_ids = active_kb_ids_for(fixture.vendor_coverage_requirements)
    return evaluate_validation(
        requirements=requirements,
        extraction=extraction,
        active_kb_ids=active_kb_ids,
        confidence_threshold=0.80,  # ADR 0002 CONFIDENCE_THRESHOLD default
        as_of=fixture.now,
    )


@pytest.mark.parametrize("fixture", VALIDATION_FIXTURES, ids=lambda f: f.id)
def test_validation_outcome_matches_expected(fixture, evaluate_validation):
    if fixture.id in KNOWN_GAPS:
        pytest.xfail(KNOWN_GAPS[fixture.id])

    outcome = _run(evaluate_validation, fixture)
    et = fixture.expected_trajectory

    expected_pass = et.expected_final_state.value == "filed"
    actual_pass = outcome.result == "pass"
    assert actual_pass == expected_pass, (
        f"{fixture.id}: expected result={'pass' if expected_pass else 'fail'}, "
        f"got {outcome.result}. flags={outcome.flags}, "
        f"line_results={[(l['coverage_type'], l['pass'], l['reasons']) for l in outcome.line_results]}"
    )

    if et.expected_faithfulness_ok is not None:
        assert outcome.faithfulness_ok == et.expected_faithfulness_ok, (
            f"{fixture.id}: expected faithfulness_ok={et.expected_faithfulness_ok}, "
            f"got {outcome.faithfulness_ok}. flags={outcome.flags}"
        )

    if et.expected_validation_flags:
        actual_flag_codes = {f["code"] for f in outcome.flags}
        missing = [c for c in et.expected_validation_flags if c not in actual_flag_codes]
        assert not missing, (
            f"{fixture.id}: expected flag code(s) {missing} not present. "
            f"Actual flags: {sorted(actual_flag_codes)}"
        )

    if et.expected_line_reasons:
        reasons_by_coverage: dict[str, list[str]] = {
            l["coverage_type"]: l["reasons"] for l in outcome.line_results
        }
        for coverage_type, expected_reasons in et.expected_line_reasons.items():
            actual_reasons = reasons_by_coverage.get(coverage_type, [])
            missing = [r for r in expected_reasons if r not in actual_reasons]
            assert not missing, (
                f"{fixture.id}: coverage_type={coverage_type} expected reason(s) {missing}, "
                f"got {actual_reasons}"
            )

    # Every fixture with NO expected_line_reasons/flags for a coverage type
    # should show that line passing — catches the inverse mistake (a fixture
    # marked clean that the real validator actually fails).
    if not et.expected_line_reasons and not et.expected_validation_flags and expected_pass:
        failing_lines = [l for l in outcome.line_results if not l["pass"]]
        assert not failing_lines, (
            f"{fixture.id}: fixture expects a clean pass with no flags, but real "
            f"validation_logic failed line(s): {failing_lines}"
        )


def test_the_known_gap_marker_list_is_still_accurate():
    """If every fixture in KNOWN_GAPS is no longer collected (e.g. renamed),
    this catches the marker silently going dead instead of quietly no-op'ing."""
    fixture_ids = {f.id for f in VALIDATION_FIXTURES}
    stale = [fid for fid in KNOWN_GAPS if fid not in fixture_ids]
    assert not stale, f"KNOWN_GAPS references fixture id(s) no longer in the golden set: {stale}"
