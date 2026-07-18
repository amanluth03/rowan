from __future__ import annotations

import os

import pytest

from tests.evals.harness.mock_clients import MockEmailClient
from tests.evals.harness.pipeline_adapter import PipelineNotAvailable, resolve_pipeline
from tests.evals.harness.retriever_adapter import RetrieverNotAvailable, resolve_retriever_class
from tests.evals.metrics.report import EvalRunReport


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "golden_document: full-trajectory golden-document fixture test (contracts/state_machine)"
    )
    config.addinivalue_line(
        "markers", "golden_real: requires ROWAN_EVAL_MODE=real and a live Claude API key; gated in CI"
    )
    config.addinivalue_line("markers", "retrieval: ADR 0005 requirements-retrieval correctness/fallback check")
    config.addinivalue_line("markers", "faithfulness: ADR 0005 structural faithfulness check")
    config.addinivalue_line("markers", "adversarial: prompt-injection golden-document fixture")
    config.addinivalue_line("markers", "fixture_integrity: fast, offline, validates the fixture set itself")


@pytest.fixture(scope="session")
def eval_mode() -> str:
    # ASSUMPTION: default mode is "mock" (fast, offline, deterministic) so the
    # fast CI job never needs API credentials. ROWAN_EVAL_MODE=real is the
    # separately-gated, slow, costs-money job (see .github/workflows/evals.yml).
    mode = os.environ.get("ROWAN_EVAL_MODE", "mock")
    if mode not in ("mock", "real"):
        raise ValueError(f"ROWAN_EVAL_MODE must be 'mock' or 'real', got {mode!r}")
    return mode


@pytest.fixture()
def pipeline():
    """The real orchestration pipeline entrypoint. Skips (not fails) the test
    if backend/agent-engineer haven't landed it yet — see harness/
    pipeline_adapter.py for the resolution contract."""
    try:
        return resolve_pipeline()
    except PipelineNotAvailable as e:
        pytest.skip(str(e))


@pytest.fixture()
def retriever_class():
    """The real V1DeterministicRetriever class. Skips if not yet implemented."""
    try:
        return resolve_retriever_class()
    except RetrieverNotAvailable as e:
        pytest.skip(str(e))


@pytest.fixture()
def mock_email_client() -> MockEmailClient:
    """Resend is NEVER live in tests/evals — this fixture is used in every
    mode, mock or real-LLM."""
    return MockEmailClient()


@pytest.fixture(scope="session")
def eval_report(eval_mode: str):
    report = EvalRunReport(mode=eval_mode)
    yield report
    report.write()
