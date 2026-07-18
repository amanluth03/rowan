"""
The seam between this eval harness and the real orchestration pipeline.

RESOLVED (integration pass, 2026-07-18): backend's real orchestration landed
at `backend/app/orchestration/runner.py` — a set of free functions
(`run_parsing`, `run_validation`, `handle_inbound_document`,
`complete_filing`, ...) operating over asyncpg + a live Postgres, not the
originally-guessed `backend.orchestration.pipeline:run_document_pipeline`
module/shape. Rather than force backend's DI pattern into the
`PipelineDependencies` bag-of-deps this file originally proposed (which
guessed at an injectable LLM client / email client / clock that don't
actually exist as seams in the real build — see `harness/real_pipeline.py`'s
module docstring for the specifics), the default entrypoint now points at a
thin real implementation in THIS package
(`tests.evals.harness.real_pipeline:run_document_pipeline`) that drives the
real runner functions directly, the same way backend-engineer's own
white-box tests do
(`backend/tests/test_orchestration_document_pipeline.py`). No eval fixture
or assertion code needed to change — only this one resolution point, exactly
as designed.

# ASSUMPTION: `ROWAN_PIPELINE_ENTRYPOINT` remains the override seam (e.g. to
# point at a future, more fully-DI'd pipeline entrypoint without touching
# this file again).
"""
from __future__ import annotations

import importlib
import os
from typing import Any, Protocol

from tests.evals.contracts.state_machine import RunTrajectory

ENV_VAR = "ROWAN_PIPELINE_ENTRYPOINT"
DEFAULT_ENTRYPOINT = "tests.evals.harness.real_pipeline:run_document_pipeline"


class PipelineNotAvailable(Exception):
    """Raised (and turned into a pytest.skip) when the real pipeline
    implementation doesn't exist yet or doesn't match the expected shape."""


class PipelineDependencies:
    """Everything the harness injects for a deterministic, offline-capable
    run. Real signature TBD with backend/agent-engineer; this is the
    proposed shape (see module docstring) so mock-mode tests can be written
    now and only need small glue changes once the real DI pattern lands.

    # ASSUMPTION: dependency injection via a single bag-of-deps object is
    # proposed, not confirmed with backend-engineer. Whatever their actual
    # pattern (FastAPI Depends, a container, explicit args), the fields below
    # are the *logical* dependencies every fixture run needs controlled:
    # an LLM client (mock or real), an email client (always mocked in CI —
    # Resend must never be hit from tests), a requirements retriever, and a
    # frozen clock (scheduler guards are date-based; fixtures pin "now").
    """

    def __init__(
        self,
        *,
        llm_client: Any,
        email_client: Any,
        requirements_retriever: Any,
        now: Any,
        db_session: Any = None,
    ) -> None:
        self.llm_client = llm_client
        self.email_client = email_client
        self.requirements_retriever = requirements_retriever
        self.now = now
        self.db_session = db_session


class PipelineUnderTest(Protocol):
    def __call__(self, fixture: Any, deps: PipelineDependencies) -> RunTrajectory: ...


def resolve_pipeline() -> PipelineUnderTest:
    """Import and return the real pipeline entrypoint, or raise
    PipelineNotAvailable with an actionable message. Callers (conftest
    fixtures) turn that into pytest.skip so the harness fails *meaningfully*
    rather than erroring out at collection time."""
    entrypoint = os.environ.get(ENV_VAR, DEFAULT_ENTRYPOINT)
    module_path, sep, func_name = entrypoint.partition(":")
    if not sep:
        raise PipelineNotAvailable(
            f"{ENV_VAR}='{entrypoint}' is malformed; expected 'module.path:function_name'."
        )
    try:
        module = importlib.import_module(module_path)
        fn = getattr(module, func_name)
    except (ImportError, ModuleNotFoundError, AttributeError) as e:
        raise PipelineNotAvailable(
            f"Pipeline entrypoint '{entrypoint}' not found ({type(e).__name__}: {e}). "
            f"This is expected until backend/agent-engineer land the orchestration "
            f"pipeline. Implement a callable matching "
            f"harness.pipeline_adapter.PipelineUnderTest at this path, or set "
            f"{ENV_VAR} to the correct 'module:function'."
        ) from e
    return fn
