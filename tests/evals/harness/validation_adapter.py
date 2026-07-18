"""
Seam onto `app.tools.validation_logic.evaluate_validation` — the ONE piece
of the pipeline that landed as a pure, DB-free, LLM-free function while the
rest of orchestration was still being built. Unlike pipeline_adapter.py /
retriever_adapter.py (which target code that doesn't exist yet, or that
needs a live DB connection respectively), this seam is genuinely callable
today, so test_validation_logic.py exercises it for real rather than
skipping.

Same resolution pattern as the sibling adapters for consistency + so this
degrades gracefully (skip, not collection error) if backend restructures the
module later.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

ENV_VAR = "ROWAN_VALIDATION_ENTRYPOINT"
DEFAULT_ENTRYPOINT = "app.tools.validation_logic:evaluate_validation"

# Confirmed by reading backend/app/tools/validation_logic.py directly (not a
# guess like the other two adapters' defaults): backend/pyproject.toml has
# `package = false` and every backend module imports as `app.*`, so `app` is
# only importable with `backend/` itself on sys.path — there is no installed
# `rowan-backend` package to `pip install`. We add it defensively here
# rather than requiring every CI job to set PYTHONPATH by hand.
_BACKEND_SRC = Path(__file__).resolve().parents[3] / "backend"
if _BACKEND_SRC.is_dir() and str(_BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(_BACKEND_SRC))


class ValidationLogicNotAvailable(Exception):
    pass


def resolve_evaluate_validation() -> Any:
    entrypoint = os.environ.get(ENV_VAR, DEFAULT_ENTRYPOINT)
    module_path, sep, func_name = entrypoint.partition(":")
    if not sep:
        raise ValidationLogicNotAvailable(
            f"{ENV_VAR}='{entrypoint}' is malformed; expected 'module.path:function_name'."
        )
    try:
        module = importlib.import_module(module_path)
        fn = getattr(module, func_name)
    except (ImportError, ModuleNotFoundError, AttributeError) as e:
        raise ValidationLogicNotAvailable(
            f"Validation entrypoint '{entrypoint}' not found ({type(e).__name__}: {e}). "
            f"Expected at backend/app/tools/validation_logic.py:evaluate_validation "
            f"(confirmed present as of this harness's last check) — if it moved, set "
            f"{ENV_VAR}, or backend/ isn't checked out at the expected sibling path "
            f"({_BACKEND_SRC})."
        ) from e
    return fn
