"""Coverage-gap explanation drafting — the second LLM call named in
CLAUDE.md's canonical document pipeline ("coverage-gap explanation drafting
... turns deterministic validation flags into human-readable prose") and in
ADR 0002 (`validating -> needs_human_review`/`escalated_to_pm`: "The LLM-
drafted explanation is attached to the escalation but does not change the
routing"). `Action.draft_explanation` already exists in
`app/policy/actions.py`'s `validating` allowlist and in
`app/policy/guardrails.py`'s `LLM_ACTIONS` (backend-engineer left this hook
for agent-engineer, per ADR 0004's amendment).

This is DESCRIPTIVE ONLY. The pass/fail/faithfulness decision already
happened in `app.tools.validation_logic.evaluate_validation` (pure,
deterministic, no LLM) before this ever runs. This tool never sees the raw
document or decides anything — it takes the deterministic flags/line_results
`update_coi_record` already computed and writes a PM-facing paragraph. If
this call fails or the per-document LLM budget is exhausted, the caller
(`app/orchestration/runner.py`) MUST fall back to a deterministic templated
summary and proceed with escalation anyway — ADR 0004: "never gates the
escalation."

Guardrail note: `line_results`/`flags` are DETERMINISTIC, typed data (ints,
bools, dates, closed-vocabulary reason codes) computed by
`evaluate_validation`, not raw document text — the injection surface that
matters for `parse_document` doesn't really exist here. The one exception is
`extraction_notes` (the extraction pass's free-text `notes` field, which MAY
quote/describe document content, including a document's own attempt at
injection). Treated as untrusted anyway, delimiter-wrapped, defense in
depth — cheap insurance against a compounding injection path.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.db import org_scoped_tx
from app.models.enums import EventSeverity, EventType, ToolStatus
from app.models.tool_contracts import PendingEvent, ToolContext, ToolOutput
from app.policy.file_guardrails import wrap_untrusted_document_text
from app.retrieval import run_repo
from app.tools import idempotency, keys

TOOL_NAME = "draft_explanation"


class DraftExplanationEngineResult(BaseModel):
    explanation_text: str
    model: str
    prompt_hash: str
    input_tokens: int
    output_tokens: int
    cost_cents: int


class ExplanationEngineError(Exception):
    """Raised by an ExplanationEngine implementation on any provider/schema
    failure. Caller MUST fall back to a deterministic summary — this is a
    descriptive-only call, never a blocking one."""


class ExplanationEngine:
    """Protocol-shaped like ExtractionEngine (see app/tools/parse_document.py)
    — duck-typed so `app/tools/explanation_engine.py::ClaudeExplanationEngine`
    can be swapped in via DI without a formal Protocol import cycle."""

    async def draft(
        self,
        *,
        vendor_name: str,
        result: str,
        line_results: list[dict[str, Any]],
        flags: list[dict[str, Any]],
        faithfulness_ok: bool,
        extraction_notes: str | None,
    ) -> DraftExplanationEngineResult: ...


class StubExplanationEngine:
    async def draft(self, **kwargs: Any) -> DraftExplanationEngineResult:
        raise NotImplementedError(
            "StubExplanationEngine: no real ExplanationEngine wired. See "
            "app/tools/explanation_engine.py::ClaudeExplanationEngine."
        )


class DraftExplanationInput(BaseModel):
    coi_validation_id: UUID
    vendor_name: str
    result: str
    line_results: list[dict[str, Any]]
    flags: list[dict[str, Any]]
    faithfulness_ok: bool
    extraction_notes: str | None = None


class DraftExplanationData(BaseModel):
    explanation_text: str
    model: str
    prompt_hash: str
    cost_cents: int


async def draft_explanation(
    context: ToolContext,
    input: DraftExplanationInput,
    *,
    engine: ExplanationEngine | None = None,
) -> ToolOutput[DraftExplanationData]:
    """Best-effort, budget-gated, descriptive-only. Caller is responsible for
    checking policy (`Action.draft_explanation`, shares the per-document LLM
    budget with `parse_document` per `app/policy/guardrails.py::LLM_ACTIONS`)
    BEFORE calling this — exactly the same division of responsibility as
    `run_parsing`'s guard-then-call pattern for `parse_document`. A `failed`
    result here must never block or alter the escalation it's attached to.
    """
    engine = engine or StubExplanationEngine()

    idempotency_key = keys.sha256(f"{input.coi_validation_id}|explain")
    request_hash = keys.sha256(f"{input.coi_validation_id}|{input.result}|{input.faithfulness_ok}")

    async with org_scoped_tx(context.organization_id) as conn:
        outcome = await idempotency.reserve(
            conn,
            organization_id=context.organization_id,
            run_id=context.run_id,
            tool_name=TOOL_NAME,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
    if not outcome.proceed:
        if outcome.replay and outcome.stored_status == "succeeded":
            return ToolOutput(
                status=ToolStatus.ok, idempotent_replay=True, data=DraftExplanationData(**outcome.stored_response)
            )
        if outcome.replay:
            return ToolOutput(status=ToolStatus.failed, idempotent_replay=True, reason="prior attempt failed")
        return ToolOutput(status=ToolStatus.denied, reason="invocation already in progress")

    # Defense in depth: any document-derived free text is wrapped even
    # though it's already once-removed from the raw document (see module
    # docstring).
    wrapped_notes = wrap_untrusted_document_text(input.extraction_notes) if input.extraction_notes else None

    try:
        result = await engine.draft(
            vendor_name=input.vendor_name,
            result=input.result,
            line_results=input.line_results,
            flags=input.flags,
            faithfulness_ok=input.faithfulness_ok,
            extraction_notes=wrapped_notes,
        )
    except ExplanationEngineError as e:
        async with org_scoped_tx(context.organization_id) as conn:
            await idempotency.complete(conn, outcome.invocation_id, status="failed", error={"reason": str(e)})
            await run_repo.increment_counters(conn, context.run_id, llm_call_delta=1)
        return ToolOutput(status=ToolStatus.failed, reason=str(e))
    except NotImplementedError as e:
        async with org_scoped_tx(context.organization_id) as conn:
            await idempotency.complete(
                conn, outcome.invocation_id, status="failed", error={"reason": "explanation_engine_not_wired"}
            )
        return ToolOutput(status=ToolStatus.failed, reason=str(e))

    data = DraftExplanationData(
        explanation_text=result.explanation_text,
        model=result.model,
        prompt_hash=result.prompt_hash,
        cost_cents=result.cost_cents,
    )

    async with org_scoped_tx(context.organization_id) as conn:
        await run_repo.increment_counters(
            conn, context.run_id, llm_call_delta=1, cost_cents_delta=result.cost_cents
        )
        await idempotency.complete(
            conn, outcome.invocation_id, status="succeeded", response=data.model_dump(mode="json")
        )

    return ToolOutput(
        status=ToolStatus.ok,
        data=data,
        events=[
            PendingEvent(
                event_type=EventType.llm_call,
                name="draft_explanation.drafted",
                severity=EventSeverity.info,
                tool_name=TOOL_NAME,
                idempotency_key=idempotency_key,
                llm_model=result.model,
                prompt_hash=result.prompt_hash,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_cents=result.cost_cents,
                payload={"coi_validation_id": str(input.coi_validation_id)},
            )
        ],
    )
