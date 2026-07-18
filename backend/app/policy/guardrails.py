"""Policy/safety layer (layer 5): allowlists + guardrails + kill switches +
budgets, as pure functions returning allow/deny + reason (ADR 0003:
"No I/O side effects of its own except reading config/flags; returns
allow/deny + reason"). Callers (orchestration, tools/base.py) MUST honor a
deny — this module never performs the DB write, email send, etc. itself.

Kill-switch priority (ADR 0002 "Global rules", 0-priority):
    1. global env flag `ROWAN_KILL_SWITCH`      -> halts ALL orgs' outbound.
    2. per-org `organizations.agent_enabled`    -> freezes one org.
    3. per-run `runs.status == 'paused'`        -> freezes one run (PM takeover).
A frozen run takes no action and stays in its current state until resumed.
Reads still run under all three (only outbound/side-effecting actions are
denied).
"""

from __future__ import annotations

from pydantic import BaseModel

from app.config import settings
from app.models.enums import RunState, RunStatus
from app.models.tool_contracts import BudgetSnapshot
from app.policy.actions import ACTION_ALLOWLIST, Action

# Actions that perform no outbound/side-effecting work — always exempt from
# kill-switch denial (reads keep running per ADR 0002).
READ_ONLY_ACTIONS = frozenset({Action.evaluate_expiry, Action.wait})

# Which budget dimension(s) each action consumes. Actions not listed consume
# none (e.g. transition, wait, log_error, notify_pm_handled to the PM which
# per ADR 0004 "does not count against the 3-vendor-outreach cap").
OUTREACH_ACTIONS = frozenset({Action.send_first_outreach, Action.follow_up_within_budget})
LLM_ACTIONS = frozenset({Action.parse_document, Action.draft_explanation})
# Every side-effecting action is cost-capped; outreach/LLM actions are also
# cost-capped on top of their own dimension.
COST_CAPPED_ACTIONS = OUTREACH_ACTIONS | LLM_ACTIONS


class PolicyDecision(BaseModel):
    allow: bool
    reason: str | None = None
    guardrail_name: str | None = None

    @classmethod
    def allowed(cls) -> "PolicyDecision":
        return cls(allow=True)

    @classmethod
    def denied(cls, reason: str, guardrail_name: str) -> "PolicyDecision":
        return cls(allow=False, reason=reason, guardrail_name=guardrail_name)


def check_kill_switches(
    *, org_agent_enabled: bool, run_status: RunStatus, action: Action
) -> PolicyDecision:
    if action in READ_ONLY_ACTIONS:
        return PolicyDecision.allowed()

    if settings.rowan_kill_switch:
        return PolicyDecision.denied(
            "global kill switch active (ROWAN_KILL_SWITCH)", "global_kill_switch"
        )
    if not org_agent_enabled:
        return PolicyDecision.denied(
            "organization agent disabled (organizations.agent_enabled=false)",
            "org_agent_disabled",
        )
    if run_status == RunStatus.paused:
        return PolicyDecision.denied("run paused for PM takeover", "run_paused")
    if run_status in (RunStatus.completed, RunStatus.errored):
        return PolicyDecision.denied(f"run status is {run_status.value}", "run_not_active")
    return PolicyDecision.allowed()


def check_allowlist(state: RunState, action: Action) -> PolicyDecision:
    if action not in ACTION_ALLOWLIST.get(state, frozenset()):
        return PolicyDecision.denied(
            f"action '{action.value}' is not in the allowlist for state '{state.value}'",
            "action_not_allowlisted",
        )
    return PolicyDecision.allowed()


def check_budget(action: Action, budget: BudgetSnapshot, *, additional_cost_cents: int = 0) -> PolicyDecision:
    if action in OUTREACH_ACTIONS and not budget.outreach_budget_ok():
        return PolicyDecision.denied(
            f"outreach budget exhausted ({budget.outreach_email_count}/{budget.max_outreach})",
            "outreach_budget_exhausted",
        )
    if action in LLM_ACTIONS and not budget.llm_budget_ok():
        return PolicyDecision.denied(
            f"LLM-per-document budget exhausted "
            f"({budget.llm_calls_this_doc}/{budget.max_llm_per_doc})",
            "llm_budget_exhausted",
        )
    if action in COST_CAPPED_ACTIONS and not budget.cost_budget_ok(additional_cost_cents):
        return PolicyDecision.denied(
            f"cost budget exhausted ({budget.cost_cents_spent}c / "
            f"{budget.budget_cost_cap_cents}c cap)",
            "cost_budget_exhausted",
        )
    return PolicyDecision.allowed()


def check_action(
    *,
    state: RunState,
    action: Action,
    org_agent_enabled: bool,
    run_status: RunStatus,
    budget: BudgetSnapshot,
    additional_cost_cents: int = 0,
) -> PolicyDecision:
    """The single entry point tools/orchestration call before any
    side-effecting action. Order matters: allowlist first (an action outside
    the allowlist is a guardrail trip regardless of budget/kill state), then
    kill switches, then budget.
    """

    decision = check_allowlist(state, action)
    if not decision.allow:
        return decision

    decision = check_kill_switches(
        org_agent_enabled=org_agent_enabled, run_status=run_status, action=action
    )
    if not decision.allow:
        return decision

    return check_budget(action, budget, additional_cost_cents=additional_cost_cents)
