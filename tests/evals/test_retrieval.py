"""
ADR 0005 retrieval-correctness and fallback checks against the REAL
`RequirementsRetriever` implementation, once one exists (see
harness/retriever_adapter.py — skips meaningfully until then). Fixture
design/expected values live in fixtures/retrieval_cases.py and are already
sanity-checked (without any implementation) in test_fixture_integrity.py.
"""
from __future__ import annotations

import pytest

from tests.evals.fixtures.org_context.base_org import COMPLIANCE_REQUIREMENTS_KB
from tests.evals.fixtures.retrieval_cases import RETRIEVAL_CASES

pytestmark = pytest.mark.retrieval


@pytest.mark.parametrize("case", RETRIEVAL_CASES, ids=lambda c: c.id)
def test_retrieval_matches_expected(case, retriever_class):
    # ASSUMPTION: the real retriever's constructor signature is unknown; this
    # assumes `retriever_class(kb_rows=...)` or a zero-arg constructor that
    # reads from an injected/seeded DB. Whichever backend-engineer lands,
    # this call site needs to change — the KB fixture data and expected
    # results (fixtures/retrieval_cases.py, org_context/base_org.py) do not.
    try:
        retriever = retriever_class(kb_rows=COMPLIANCE_REQUIREMENTS_KB)
    except TypeError:
        retriever = retriever_class()

    result = retriever.retrieve(case.query)

    assert result.found == case.expected_found, (
        f"{case.id}: expected found={case.expected_found}, got {result.found}"
    )
    if not case.expected_found:
        assert result.requirements == [], f"{case.id}: found=False must pair with an empty requirements list"
        return

    by_coverage = {r.coverage_type.value: r.id for r in result.requirements}
    assert by_coverage == case.expected_winning_ids_by_coverage, (
        f"{case.id}: {case.reasoning}\n"
        f"expected {case.expected_winning_ids_by_coverage}, got {by_coverage}"
    )
    # Reduce-to-one-row-per-coverage-type invariant (ADR 0005).
    coverage_types = [r.coverage_type for r in result.requirements]
    assert len(coverage_types) == len(set(coverage_types)), (
        f"{case.id}: retriever returned more than one row for the same coverage_type: {coverage_types}"
    )


def test_fallback_query_returns_empty_list_not_none(retriever_class):
    """Structural guard: found=False must pair with requirements=[], never
    None or a partial list — the state machine's guard (ADR 0002 validating
    -> escalated_to_pm) checks `found`, but a sloppy implementation that
    also leaves `requirements` non-empty on a fallback would let a later
    accidental read silently use stale/wrong data."""
    fallback_case = next(c for c in RETRIEVAL_CASES if not c.expected_found)
    try:
        retriever = retriever_class(kb_rows=COMPLIANCE_REQUIREMENTS_KB)
    except TypeError:
        retriever = retriever_class()
    result = retriever.retrieve(fallback_case.query)
    assert result.requirements == []
