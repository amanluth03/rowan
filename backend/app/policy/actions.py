"""The action vocabulary and per-state allowlists (ADR 0002).

`Action` is the semantic action the orchestration layer proposes ("follow up
within budget"), which may wrap one or more tool calls underneath (e.g.
`follow_up_within_budget` wraps the `send_email` tool with the follow_up
template plus the outreach-budget check). Allowlists are enforced against
`Action`, not against raw tool names, so a state can permit `send_email` in
one semantic shape (first outreach) while denying it in another (an
out-of-band send outside the allowed action) even though both would call the
same underlying tool.

This is deliberately DATA (a dict), not scattered `if state == ...` checks,
per CLAUDE.md: "per-state action allowlists enforced in code (not by
convention)."
"""

from __future__ import annotations

from enum import Enum

from app.models.enums import RunState


class Action(str, Enum):
    # monitoring
    evaluate_expiry = "evaluate_expiry"

    # renewal_due_soon
    send_first_outreach = "send_first_outreach"

    # first_outreach_sent (transient bookkeeping state)
    record_outreach_sent = "record_outreach_sent"

    # awaiting_vendor_response — CLAUDE.md's canonical example, EXACTLY three
    wait = "wait"
    follow_up_within_budget = "follow_up_within_budget"

    # document_received
    classify_and_store_document = "classify_and_store_document"

    # parsing
    parse_document = "parse_document"

    # validating
    run_validation = "run_validation"
    draft_explanation = "draft_explanation"

    # filed
    file_document = "file_document"
    mark_task_complete = "mark_task_complete"
    notify_pm_handled = "notify_pm_handled"

    # needs_human_review / escalated_to_pm
    create_or_update_escalation = "create_or_update_escalation"
    notify_pm = "notify_pm"

    # escalate (available from several states per ADR 0002)
    escalate_to_pm = "escalate_to_pm"

    # errored
    log_error = "log_error"

    # generic: advance to the next state once a guard has already passed.
    # Every state's allowlist includes this; it performs no side effect of
    # its own (the side effect already happened via one of the actions
    # above) — it is the runner writing the state_transition event + new
    # `runs.state` atomically. See app/orchestration/runner.py.
    transition = "transition"


ACTION_ALLOWLIST: dict[RunState, frozenset[Action]] = {
    RunState.monitoring: frozenset({Action.evaluate_expiry, Action.transition}),
    RunState.renewal_due_soon: frozenset(
        {Action.send_first_outreach, Action.escalate_to_pm, Action.transition}
    ),
    RunState.first_outreach_sent: frozenset(
        {Action.record_outreach_sent, Action.transition}
    ),
    # EXACTLY three, per CLAUDE.md's canonical example.
    RunState.awaiting_vendor_response: frozenset(
        {Action.wait, Action.follow_up_within_budget, Action.escalate_to_pm}
    ),
    RunState.document_received: frozenset(
        {Action.classify_and_store_document, Action.escalate_to_pm, Action.transition}
    ),
    RunState.parsing: frozenset({Action.parse_document, Action.transition}),
    RunState.validating: frozenset(
        {
            Action.run_validation,
            Action.draft_explanation,
            Action.escalate_to_pm,
            Action.transition,
        }
    ),
    RunState.filed: frozenset(
        {
            Action.file_document,
            Action.mark_task_complete,
            Action.notify_pm_handled,
            Action.transition,
        }
    ),
    RunState.needs_human_review: frozenset(
        {Action.create_or_update_escalation, Action.notify_pm, Action.wait, Action.transition}
    ),
    RunState.escalated_to_pm: frozenset(
        {Action.create_or_update_escalation, Action.notify_pm, Action.wait, Action.transition}
    ),
    RunState.errored: frozenset({Action.log_error, Action.notify_pm, Action.wait}),
}


def is_allowed(state: RunState, action: Action) -> bool:
    return action in ACTION_ALLOWLIST.get(state, frozenset())
