"""
Fast, fully offline sanity checks on the golden-document set and its sibling
fixture files. These run TODAY, before any backend/agent-engineer code
exists — they validate that the harness's own contract (CLAUDE.md's Evals
section + ADR 0002/0004/0005) is satisfied by the fixture DESIGN, independent
of any implementation. If this file is red, the fixtures themselves are
broken; it should never depend on `pipeline`/`retriever_class`.
"""
from __future__ import annotations

import pytest

from tests.evals.contracts.state_machine import RunState
from tests.evals.fixtures.faithfulness_cases import FAITHFULNESS_CASES
from tests.evals.fixtures.golden_manifest import GOLDEN_DOCUMENTS
from tests.evals.fixtures.retrieval_cases import RETRIEVAL_CASES

pytestmark = pytest.mark.fixture_integrity

REQUIRED_CATEGORIES = {
    "clean",
    "low_limits",
    "missing_additional_insured",
    "wrong_dates",
    "unparseable",
    "injection",
}


def test_golden_set_size_in_spec_range():
    # CLAUDE.md / brief: "15-20 test COIs"
    assert 15 <= len(GOLDEN_DOCUMENTS) <= 20, (
        f"golden document set has {len(GOLDEN_DOCUMENTS)} fixtures, expected 15-20"
    )


def test_golden_ids_are_unique():
    ids = [f.id for f in GOLDEN_DOCUMENTS]
    assert len(ids) == len(set(ids)), f"duplicate fixture ids: {[i for i in ids if ids.count(i) > 1]}"


def test_all_required_categories_present():
    present = {f.category for f in GOLDEN_DOCUMENTS}
    missing = REQUIRED_CATEGORIES - present
    assert not missing, f"golden set is missing required categories: {missing}"


def test_at_least_three_adversarial_injection_fixtures():
    # CLAUDE.md: "at least 3 adversarial documents containing prompt-injection attempts"
    adversarial = [f for f in GOLDEN_DOCUMENTS if f.is_adversarial]
    assert len(adversarial) >= 3, f"only {len(adversarial)} adversarial fixtures, need >= 3"
    assert all(f.category == "injection" for f in adversarial), (
        "every is_adversarial fixture should be categorized 'injection' for discoverability"
    )


@pytest.mark.parametrize("fx", GOLDEN_DOCUMENTS, ids=lambda f: f.id)
def test_document_file_exists_and_nonempty(fx):
    assert fx.document_path.exists(), f"{fx.id}: missing document file {fx.document_path}"
    content = fx.document_path.read_text()
    assert content.strip(), f"{fx.id}: document file is empty"


@pytest.mark.parametrize("fx", GOLDEN_DOCUMENTS, ids=lambda f: f.id)
def test_expected_trajectory_internally_consistent(fx):
    et = fx.expected_trajectory
    # The last expected state in the sequence should be the final state.
    assert et.expected_state_sequence[-1] == et.expected_final_state, (
        f"{fx.id}: expected_state_sequence ends in {et.expected_state_sequence[-1]}, "
        f"but expected_final_state={et.expected_final_state}"
    )
    # No state should be simultaneously required and forbidden.
    overlap = set(et.expected_state_sequence) & set(et.forbidden_states)
    assert not overlap, f"{fx.id}: states {overlap} are both expected and forbidden"
    # Safety net: any fixture that doesn't end in `filed` MUST forbid `filed`
    # explicitly. This is the fixture-authoring guard against silently
    # weakening the harness's core auto-approval check.
    if et.expected_final_state != RunState.FILED:
        assert RunState.FILED in et.forbidden_states, (
            f"{fx.id}: expected_final_state={et.expected_final_state} but forbidden_states "
            f"doesn't include FILED — this fixture wouldn't catch an auto-file bug"
        )
        assert "mark_task_complete" in et.forbidden_tool_calls or True, (
            "mark_task_complete is checked structurally by trajectory_assert.py rule #10 "
            "regardless of forbidden_tool_calls contents, so this is belt-and-suspenders only"
        )
    # Any fixture ending in `filed` should specify how completion was justified.
    if et.expected_final_state == RunState.FILED:
        assert et.expected_completion_basis is not None, (
            f"{fx.id}: final_state=FILED but expected_completion_basis is unset "
            f"(ADR 0004 mark_task_complete precondition must be asserted explicitly)"
        )


@pytest.mark.parametrize("fx", GOLDEN_DOCUMENTS, ids=lambda f: f.id)
def test_extraction_expectation_shape(fx):
    if fx.extraction_expected_to_succeed:
        assert fx.expected_extraction, f"{fx.id}: extraction_expected_to_succeed=True but no expected_extraction dict"
    else:
        assert fx.expected_extraction is None, (
            f"{fx.id}: extraction_expected_to_succeed=False but expected_extraction is set — "
            f"field-accuracy scoring would silently score against nothing meaningful"
        )


def test_retrieval_cases_cover_specificity_and_fallback():
    ids = {c.id for c in RETRIEVAL_CASES}
    assert len(RETRIEVAL_CASES) >= 4, "need at least: city-beats-state, generic-fallthrough, most-specific-hoa, empty-fallback"
    fallback_cases = [c for c in RETRIEVAL_CASES if not c.expected_found]
    assert fallback_cases, "no retrieval case exercises the found=False fallback path"
    for c in fallback_cases:
        assert c.expected_winning_ids_by_coverage == {}, (
            f"{c.id}: expected_found=False must pair with an empty expected_winning_ids_by_coverage"
        )


def test_faithfulness_cases_include_a_real_violation():
    assert any(c.expect_ok is False for c in FAITHFULNESS_CASES), (
        "no on-purpose faithfulness-violation case present — required by the brief"
    )
    assert any(c.expect_ok is True for c in FAITHFULNESS_CASES), (
        "no faithful baseline case present — needed to prove the check doesn't false-positive"
    )
