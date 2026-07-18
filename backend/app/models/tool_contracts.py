"""Common tool envelope (ADR 0004 "Common envelope (every tool)").

Every tool in app/tools/ takes a `ToolContext` (plus a tool-specific input
struct) and returns a `ToolOutput[T]` (plus a tool-specific `data` payload).
This is the ONLY shape orchestration ever sees from a tool call — it never
sees a raw DB row, a raw Resend response, or a raw Claude API response.
"""

from __future__ import annotations

from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import EventSeverity, EventType, ToolStatus

T = TypeVar("T")


class BudgetSnapshot(BaseModel):
    """Per-run counters checked at guard/policy evaluation (ADR 0002/0004).

    Caps themselves live in orchestration/constants.py (org-overridable);
    this struct only carries the *current* counters + the caps that applied
    when the snapshot was taken, so a tool's budget check is a pure function
    of its input, not a hidden read of global config.
    """

    outreach_email_count: int
    llm_calls_this_doc: int
    cost_cents_spent: int
    max_outreach: int
    max_llm_per_doc: int
    budget_cost_cap_cents: int

    def outreach_budget_ok(self) -> bool:
        return self.outreach_email_count < self.max_outreach

    def llm_budget_ok(self) -> bool:
        return self.llm_calls_this_doc < self.max_llm_per_doc

    def cost_budget_ok(self, additional_cents: int = 0) -> bool:
        return (self.cost_cents_spent + additional_cents) < self.budget_cost_cap_cents


class ToolContext(BaseModel):
    """Carried on every tool call (ADR 0004 common envelope input)."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    organization_id: UUID
    # Advisory/tracing correlation id for this logical call (e.g. surfaced
    # in orchestration logs). NOT the authoritative dedup key — per
    # ADR 0004, each tool derives its OWN idempotency key deterministically
    # from its typed input (see app/tools/keys.py), so a tool never trusts a
    # caller-supplied key for the actual `tool_invocations` dedup decision.
    # This keeps the dedup contract owned by the tool, not by whichever
    # caller happens to construct the context.
    idempotency_key: str
    budget: BudgetSnapshot
    # True when the global/org/run kill switch has already been resolved
    # "not killed" by the caller's Policy pre-check (app/policy). Tools
    # re-assert this via app.policy.guardrails rather than trusting the
    # caller blindly — see app/tools/base.py.
    kill_switch_checked: bool = False


class PendingEvent(BaseModel):
    """An AgentEvent the tool wants appended (ADR 0003: "All layers ->
    Observability: append-only AgentEvent structs"). Tools never write
    agent_events directly — they return these, and the caller (orchestration)
    persists them in the same transaction as the tool's own side effect,
    so an event is never recorded for a side effect that didn't commit.
    """

    event_type: EventType
    name: str
    severity: EventSeverity = EventSeverity.info
    payload: dict = Field(default_factory=dict)
    tool_name: str | None = None
    idempotency_key: str | None = None
    llm_model: str | None = None
    prompt_hash: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_cents: int | None = None
    latency_ms: int | None = None


class ToolOutput(BaseModel, Generic[T]):
    """Common tool output envelope (ADR 0004)."""

    status: ToolStatus
    idempotent_replay: bool = False
    events: list[PendingEvent] = Field(default_factory=list)
    data: T | None = None
    # Populated when status in {denied, failed}.
    reason: str | None = None
    guardrail_name: str | None = None
