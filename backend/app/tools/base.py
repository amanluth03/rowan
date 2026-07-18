"""Shared tool-layer scaffolding: the policy pre-check every side-effecting
tool runs before touching the DB or an external provider (ADR 0004
"Budget/kill enforcement (shared): every side-effecting tool asks Policy
first; a denied decision returns status='denied' with reason, no side
effect, and a guardrail_trip event"), plus the BudgetSnapshot builder.

# ASSUMPTION: `runs.llm_call_count` is scoped to the document currently
under parsing in this run cycle (there is one active coi_document per run at
a time, consistent with the locked all-or-nothing/one-set-per-vendor
scoping). It is reset to 0 by the orchestration runner whenever
`document_received -> parsing` fires for a NEW coi_document_id (e.g. after a
PM-requested revision brings in a fresh document) — see
app/orchestration/runner.py. ADR 0001/0002 model this counter at the run
level, not a separate per-document table; this reset rule is how "per
document" (ADR 0002 MAX_LLM_PER_DOC) is honored on top of that schema. This
is a schema/state-machine nuance the ADRs didn't spell out — flagged to the
architect rather than silently assumed away.
"""

from __future__ import annotations


from app.models.enums import RunState, RunStatus
from app.models.tool_contracts import BudgetSnapshot, PendingEvent, ToolOutput
from app.models.enums import EventSeverity, EventType, ToolStatus
from app.orchestration.constants import RunConstants
from app.policy.actions import Action
from app.policy.guardrails import PolicyDecision, check_action
from app.retrieval.models import RunRow


def budget_snapshot(run: RunRow, constants: RunConstants) -> BudgetSnapshot:
    return BudgetSnapshot(
        outreach_email_count=run.outreach_email_count,
        llm_calls_this_doc=run.llm_call_count,
        cost_cents_spent=run.cost_cents_spent,
        max_outreach=constants.max_outreach,
        max_llm_per_doc=constants.max_llm_per_doc,
        budget_cost_cap_cents=constants.budget_cost_cap_cents,
    )


def policy_precheck(
    *,
    state: RunState,
    action: Action,
    org_agent_enabled: bool,
    run_status: RunStatus,
    budget: BudgetSnapshot,
    additional_cost_cents: int = 0,
) -> PolicyDecision:
    return check_action(
        state=state,
        action=action,
        org_agent_enabled=org_agent_enabled,
        run_status=run_status,
        budget=budget,
        additional_cost_cents=additional_cost_cents,
    )


def denied_output(decision: PolicyDecision, *, tool_name: str) -> ToolOutput:
    assert not decision.allow
    return ToolOutput(
        status=ToolStatus.denied,
        reason=decision.reason,
        guardrail_name=decision.guardrail_name,
        events=[
            PendingEvent(
                event_type=EventType.guardrail_trip,
                name=f"{tool_name}.denied",
                severity=EventSeverity.warn,
                tool_name=tool_name,
                payload={"reason": decision.reason, "guardrail": decision.guardrail_name},
            )
        ],
    )
