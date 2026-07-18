"""TDD: monitoring -> renewal_due_soon guard (ADR 0002).
Guard: now >= due_date - RENEWAL_LEAD_DAYS AND vendor active AND agent enabled.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.db import org_scoped_tx
from app.models.enums import RunState
from app.orchestration.runner import evaluate_expiry
from app.retrieval import run_repo

pytestmark = pytest.mark.asyncio


async def test_transitions_when_due_date_within_lead_window(org_and_vendor, make_run):
    run_id = await make_run(state="monitoring", due_date=date.today() + timedelta(days=10))
    result = await evaluate_expiry(org_and_vendor["org_id"], run_id, now=date.today())
    assert result is not None
    assert result.state == RunState.renewal_due_soon


async def test_no_transition_when_due_date_far_out(org_and_vendor, make_run):
    run_id = await make_run(state="monitoring", due_date=date.today() + timedelta(days=90))
    result = await evaluate_expiry(org_and_vendor["org_id"], run_id, now=date.today())
    assert result is None
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        run = await run_repo.get_run(conn, run_id)
    assert run.state == RunState.monitoring


async def test_no_transition_when_due_date_is_null(org_and_vendor, make_run):
    run_id = await make_run(state="monitoring", due_date=None)
    result = await evaluate_expiry(org_and_vendor["org_id"], run_id, now=date.today())
    assert result is None


async def test_no_transition_when_org_agent_disabled(org_and_vendor, make_run, admin_conn):
    run_id = await make_run(state="monitoring", due_date=date.today() + timedelta(days=10))
    await admin_conn.execute(
        "update organizations set agent_enabled = false where id = $1", org_and_vendor["org_id"]
    )
    result = await evaluate_expiry(org_and_vendor["org_id"], run_id, now=date.today())
    assert result is None
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        run = await run_repo.get_run(conn, run_id)
    assert run.state == RunState.monitoring  # frozen, not silently advanced


async def test_transition_writes_state_transition_event(org_and_vendor, make_run):
    run_id = await make_run(state="monitoring", due_date=date.today() + timedelta(days=10))
    await evaluate_expiry(org_and_vendor["org_id"], run_id, now=date.today())
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        events = await conn.fetch(
            "select * from agent_events where run_id = $1 and event_type = 'state_transition'", run_id
        )
    assert len(events) == 1
    assert events[0]["from_state"] == "monitoring"
    assert events[0]["to_state"] == "renewal_due_soon"
