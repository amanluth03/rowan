"""
ADR 0005 faithfulness check: runs entirely against hand-built fixtures in
fixtures/faithfulness_cases.py — no pipeline or backend code required, so
this suite is green (or meaningfully red) from day one. Includes the
on-purpose violation case the brief requires, to prove the check actually
catches a bad payload rather than rubber-stamping whatever
`faithfulness_ok` claims about itself.
"""
from __future__ import annotations

import pytest

from tests.evals.fixtures.faithfulness_cases import FAITHFULNESS_CASES
from tests.evals.harness.faithfulness_assert import check_faithfulness

pytestmark = pytest.mark.faithfulness


@pytest.mark.parametrize("case", FAITHFULNESS_CASES, ids=lambda c: c.id)
def test_faithfulness_check(case):
    result = check_faithfulness(case.retrieval, case.validation)
    assert result.ok == case.expect_ok, (
        f"{case.id}: expected ok={case.expect_ok}, got ok={result.ok}. "
        f"Reasons: {result.reasons}"
    )
    if case.expect_unbacked_ids is not None:
        assert sorted(result.unbacked_line_ids) == sorted(case.expect_unbacked_ids), (
            f"{case.id}: expected unbacked ids {case.expect_unbacked_ids}, "
            f"got {result.unbacked_line_ids}"
        )
    elif not case.expect_ok:
        assert result.unbacked_line_ids, f"{case.id}: expected some unbacked ids, got none"


def test_the_on_purpose_violation_case_exists_and_is_caught():
    """Explicit, named assertion (not just parametrized coverage) that the
    required 'violate faithfulness on purpose' case is present and fails
    the check — this is the single test a reviewer should be able to point
    to as proof the faithfulness gate works."""
    violation = next(c for c in FAITHFULNESS_CASES if c.id == "violation_unbacked_id_hidden_behind_true_flag")
    result = check_faithfulness(violation.retrieval, violation.validation)
    assert result.ok is False, "faithfulness check failed to catch the on-purpose violation"
    assert result.unbacked_line_ids, "violation case should report at least one unbacked id"
