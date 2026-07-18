"""Tests for app/policy/actions.py (allowlists) and app/policy/guardrails.py
(kill switches + budgets). This is CLAUDE.md's non-negotiable guardrail
layer: "per-state action allowlists enforced in code (not by convention)".
"""

from __future__ import annotations

from app.config import settings
from app.models.enums import RunState, RunStatus
from app.models.tool_contracts import BudgetSnapshot
from app.policy.actions import Action, is_allowed
from app.policy.guardrails import check_action, check_allowlist, check_budget, check_kill_switches


def _budget(**overrides) -> BudgetSnapshot:
    defaults = dict(
        outreach_email_count=0,
        llm_calls_this_doc=0,
        cost_cents_spent=0,
        max_outreach=3,
        max_llm_per_doc=5,
        budget_cost_cap_cents=200,
    )
    defaults.update(overrides)
    return BudgetSnapshot(**defaults)


class TestAwaitingVendorResponseAllowlist:
    """CLAUDE.md's canonical example: EXACTLY three permitted actions."""

    def test_exactly_three_actions_allowed(self):
        from app.policy.actions import ACTION_ALLOWLIST

        allowed = ACTION_ALLOWLIST[RunState.awaiting_vendor_response]
        assert allowed == {Action.wait, Action.follow_up_within_budget, Action.escalate_to_pm}

    def test_send_first_outreach_not_allowed_in_awaiting_vendor_response(self):
        assert not is_allowed(RunState.awaiting_vendor_response, Action.send_first_outreach)

    def test_file_document_not_allowed_in_awaiting_vendor_response(self):
        assert not is_allowed(RunState.awaiting_vendor_response, Action.file_document)


class TestAllowlistPerState:
    def test_mark_task_complete_only_allowed_in_filed(self):
        for state in RunState:
            if state == RunState.filed:
                assert is_allowed(state, Action.mark_task_complete)
            else:
                assert not is_allowed(state, Action.mark_task_complete)

    def test_out_of_allowlist_action_denied(self):
        decision = check_allowlist(RunState.monitoring, Action.file_document)
        assert decision.allow is False
        assert decision.guardrail_name == "action_not_allowlisted"


class TestKillSwitches:
    def test_global_kill_switch_blocks_outbound_action(self, monkeypatch):
        monkeypatch.setattr(settings, "rowan_kill_switch", True)
        decision = check_kill_switches(
            org_agent_enabled=True, run_status=RunStatus.active, action=Action.send_first_outreach
        )
        assert decision.allow is False
        assert decision.guardrail_name == "global_kill_switch"

    def test_global_kill_switch_does_not_block_reads(self, monkeypatch):
        monkeypatch.setattr(settings, "rowan_kill_switch", True)
        decision = check_kill_switches(
            org_agent_enabled=True, run_status=RunStatus.active, action=Action.evaluate_expiry
        )
        assert decision.allow is True

    def test_org_disabled_blocks_action(self):
        decision = check_kill_switches(
            org_agent_enabled=False, run_status=RunStatus.active, action=Action.send_first_outreach
        )
        assert decision.allow is False
        assert decision.guardrail_name == "org_agent_disabled"

    def test_paused_run_blocks_action(self):
        decision = check_kill_switches(
            org_agent_enabled=True, run_status=RunStatus.paused, action=Action.follow_up_within_budget
        )
        assert decision.allow is False
        assert decision.guardrail_name == "run_paused"

    def test_active_run_enabled_org_no_kill_switch_allows(self):
        decision = check_kill_switches(
            org_agent_enabled=True, run_status=RunStatus.active, action=Action.send_first_outreach
        )
        assert decision.allow is True


class TestBudgets:
    def test_outreach_budget_exhausted_denies(self):
        budget = _budget(outreach_email_count=3, max_outreach=3)
        decision = check_budget(Action.follow_up_within_budget, budget)
        assert decision.allow is False
        assert decision.guardrail_name == "outreach_budget_exhausted"

    def test_outreach_budget_remaining_allows(self):
        budget = _budget(outreach_email_count=2, max_outreach=3)
        decision = check_budget(Action.follow_up_within_budget, budget)
        assert decision.allow is True

    def test_llm_budget_exhausted_denies(self):
        budget = _budget(llm_calls_this_doc=5, max_llm_per_doc=5)
        decision = check_budget(Action.parse_document, budget)
        assert decision.allow is False
        assert decision.guardrail_name == "llm_budget_exhausted"

    def test_cost_budget_exhausted_denies(self):
        budget = _budget(cost_cents_spent=200, budget_cost_cap_cents=200)
        decision = check_budget(Action.parse_document, budget)
        assert decision.allow is False
        assert decision.guardrail_name == "cost_budget_exhausted"

    def test_non_capped_action_always_allowed_regardless_of_budget(self):
        budget = _budget(outreach_email_count=99, llm_calls_this_doc=99, cost_cents_spent=99999)
        decision = check_budget(Action.wait, budget)
        assert decision.allow is True


class TestCheckActionOrdering:
    """Allowlist is checked before kill switch before budget — an
    out-of-allowlist action is a guardrail trip regardless of budget state."""

    def test_allowlist_checked_first(self):
        budget = _budget(outreach_email_count=0)
        decision = check_action(
            state=RunState.monitoring,
            action=Action.file_document,
            org_agent_enabled=True,
            run_status=RunStatus.active,
            budget=budget,
        )
        assert decision.allow is False
        assert decision.guardrail_name == "action_not_allowlisted"

    def test_budget_breach_routes_to_denied_not_silent(self):
        budget = _budget(outreach_email_count=3, max_outreach=3)
        decision = check_action(
            state=RunState.awaiting_vendor_response,
            action=Action.follow_up_within_budget,
            org_agent_enabled=True,
            run_status=RunStatus.active,
            budget=budget,
        )
        assert decision.allow is False
        assert decision.guardrail_name == "outreach_budget_exhausted"

    def test_fully_allowed_action_passes(self):
        budget = _budget()
        decision = check_action(
            state=RunState.awaiting_vendor_response,
            action=Action.wait,
            org_agent_enabled=True,
            run_status=RunStatus.active,
            budget=budget,
        )
        assert decision.allow is True
