"""
The seam between this eval harness and the real orchestration pipeline.

Nothing in `backend/` or `agent/` exists yet (this harness is being built
contract-first per the tech lead's instructions). Rather than guess at
backend's internal module layout, the harness defines ONE well-known
entrypoint it will call, resolved dynamically so it degrades to a clean
`pytest.skip` (not a collection error) until that entrypoint exists.

# ASSUMPTION: the default entrypoint path `backend.orchestration.pipeline:
# run_document_pipeline` is a proposal, not something backend-engineer has
# committed to. Whoever lands the real pipeline should either (a) expose a
# callable at that path matching the `PipelineUnderTest` signature below, or
# (b) set the ROWAN_PIPELINE_ENTRYPOINT env var (or pytest.ini) to point at
# wherever it actually lives. Either way, no eval fixture or assertion code
# needs to change — only this one resolution point.
"""
from __future__ import annotations

import importlib
import os
from typing import Any, Protocol

from tests.evals.contracts.state_machine import RunTrajectory

ENV_VAR = "ROWAN_PIPELINE_ENTRYPOINT"
DEFAULT_ENTRYPOINT = "backend.orchestration.pipeline:run_document_pipeline"


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
