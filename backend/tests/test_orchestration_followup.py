"""TDD: awaiting_vendor_response self-loop (follow-up within budget) and
the escalation deadline (ADR 0002, CLAUDE.md's canonical "EXACTLY three
actions" state)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.db import org_scoped_tx
from app.models.enums import RunState
from app.orchestration.runner import check_followup_or_deadline
from app.retrieval import run_repo

pytestmark = pytest.mark.asyncio


async def test_sends_followup_when_wakeup_reached_and_budget_remains(org_and_vendor, make_run):
    run_id = await make_run(
        state="awaiting_vendor_response",
        due_date=date.today(),
        next_action_at=datetime.now(timezone.utc) - timedelta(hours=1),
        outreach_email_count=1,
    )
    result = await check_followup_or_deadline(org_and_vendor["org_id"], run_id)
    assert result is not None
    assert result.state == RunState.awaiting_vendor_response  # self-loop
    assert result.outreach_email_count == 2
    assert result.next_action_at > datetime.now(timezone.utc)


async def test_no_action_before_wakeup_time(org_and_vendor, make_run):
    run_id = await make_run(
        state="awaiting_vendor_response",
        due_date=date.today(),
        next_action_at=datetime.now(timezone.utc) + timedelta(days=1),
        outreach_email_count=1,
    )
    result = await check_followup_or_deadline(org_and_vendor["org_id"], run_id)
    assert result is None


async def test_escalates_when_max_outreach_reached(org_and_vendor, make_run):
    run_id = await make_run(
        state="awaiting_vendor_response",
        due_date=date.today(),
        next_action_at=datetime.now(timezone.utc) - timedelta(hours=1),
        outreach_email_count=3,  # == MAX_OUTREACH
    )
    result = await check_followup_or_deadline(org_and_vendor["org_id"], run_id)
    assert result is not None
    assert result.state == RunState.escalated_to_pm

    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        escalations = await conn.fetch("select * from escalations where run_id = $1", run_id)
    assert escalations[0]["reason_code"] == "no_response"


async def test_escalates_when_response_deadline_passed(org_and_vendor, make_run):
    run_id = await make_run(
        state="awaiting_vendor_response",
        due_date=date.today() - timedelta(days=20),  # deadline (14d) long passed
        next_action_at=datetime.now(timezone.utc) - timedelta(hours=1),
        outreach_email_count=1,
    )
    result = await check_followup_or_deadline(org_and_vendor["org_id"], run_id)
    assert result is not None
    assert result.state == RunState.escalated_to_pm


async def test_replay_after_followup_is_noop(org_and_vendor, make_run):
    run_id = await make_run(
        state="awaiting_vendor_response",
        due_date=date.today(),
        next_action_at=datetime.now(timezone.utc) - timedelta(hours=1),
        outreach_email_count=1,
    )
    r1 = await check_followup_or_deadline(org_and_vendor["org_id"], run_id)
    assert r1.outreach_email_count == 2

    # Immediately calling again (simulating a duplicate scheduler tick)
    # must not send a second follow-up: next_action_at just moved to the
    # future, so the guard no longer holds.
    r2 = await check_followup_or_deadline(org_and_vendor["org_id"], run_id)
    assert r2 is None

    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        run = await run_repo.get_run(conn, run_id)
    assert run.outreach_email_count == 2
