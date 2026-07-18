"""
The seam between this eval harness and the real `RequirementsRetriever`
(ADR 0005). Same resolution pattern as `pipeline_adapter.py`: try to import a
well-known entrypoint, skip meaningfully if it isn't there yet.
"""
from __future__ import annotations

import importlib
import os
from typing import Any

ENV_VAR = "ROWAN_RETRIEVER_ENTRYPOINT"
# ASSUMPTION: proposed default path for the v1 deterministic retriever class
# (ADR 0005 `V1DeterministicRetriever`). Not confirmed with backend/
# agent-engineer — see pipeline_adapter.py's note on the same pattern.
DEFAULT_ENTRYPOINT = "backend.retrieval.requirements:V1DeterministicRetriever"


class RetrieverNotAvailable(Exception):
    pass


def resolve_retriever_class() -> Any:
    entrypoint = os.environ.get(ENV_VAR, DEFAULT_ENTRYPOINT)
    module_path, sep, cls_name = entrypoint.partition(":")
    if not sep:
        raise RetrieverNotAvailable(
            f"{ENV_VAR}='{entrypoint}' is malformed; expected 'module.path:ClassName'."
        )
    try:
        module = importlib.import_module(module_path)
        cls = getattr(module, cls_name)
    except (ImportError, ModuleNotFoundError, AttributeError) as e:
        raise RetrieverNotAvailable(
            f"Retriever entrypoint '{entrypoint}' not found ({type(e).__name__}: {e}). "
            f"Expected until backend/agent-engineer land ADR 0005's "
            f"V1DeterministicRetriever. Implement the RequirementsRetriever "
            f"Protocol (tests/evals/contracts/retrieval.py) at this path, or set "
            f"{ENV_VAR}."
        ) from e
    return cls
