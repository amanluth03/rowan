"""
The seam between this eval harness and the real `RequirementsRetriever`
(ADR 0005). Same resolution pattern as `pipeline_adapter.py`: try to import a
well-known entrypoint, skip meaningfully if it isn't there yet.

RESOLVED by agent-engineer (2026-07-18): the production implementation is
`app.retrieval.requirements_retriever.V1DeterministicRetriever` (in
`backend/`, not `backend/app/retrieval/requirements.py` as this file's old
placeholder guessed) — but it takes an `asyncpg.Connection` and exposes an
`async def retrieve()`, whereas THIS harness's `test_retrieval.py` calls
`retriever_class(kb_rows=...)` and `retriever.retrieve(query)` synchronously,
with no Postgres involved. Pointing this at the production class as-is would
break the harness's own contract (a coroutine object back where a
`RetrievalResult` is expected). `harness/offline_retriever.py` is the
resolution: the SAME predicate-match + specificity-ranking algorithm,
reimplemented in plain Python over in-memory `kb_rows`, matching the
`kb_rows=`/sync-`retrieve()` shape this test file already expects — see that
module's docstring for the full "why a second file" reasoning and its one
fixture-coupling ASSUMPTION. Retrieval CORRECTNESS is verified against the
real production class separately, in backend's own live-Postgres suite
(`backend/tests/test_requirements_retriever.py`).
"""
from __future__ import annotations

import importlib
import os
from typing import Any

ENV_VAR = "ROWAN_RETRIEVER_ENTRYPOINT"
DEFAULT_ENTRYPOINT = "tests.evals.harness.offline_retriever:V1DeterministicRetriever"


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
