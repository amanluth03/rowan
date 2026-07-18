"""TDD: renewal_due_soon -> first_outreach_sent -> awaiting_vendor_response
(ADR 0002), and the escalation path when the vendor has no contact email.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.db import org_scoped_tx
from app.models.enums import RunState
from app.orchestration.runner import send_first_outreach
from app.retrieval import run_repo

pytestmark = pytest.mark.asyncio


async def test_sends_outreach_and_cascades_to_awaiting_vendor_response(org_and_vendor, make_run):
    run_id = await make_run(state="renewal_due_soon", due_date=date.today())
    result = await send_first_outreach(org_and_vendor["org_id"], run_id)
    assert result is not None
    assert result.state == RunState.awaiting_vendor_response
    assert result.outreach_email_count == 1
    assert result.next_action_at is not None


async def test_escalates_when_vendor_has_no_primary_email(org_and_vendor, make_run, admin_conn):
    await admin_conn.execute(
        "update vendors set primary_email = null where id = $1", org_and_vendor["vendor_id"]
    )
    run_id = await make_run(state="renewal_due_soon", due_date=date.today())
    result = await send_first_outreach(org_and_vendor["org_id"], run_id)
    assert result is not None
    assert result.state == RunState.escalated_to_pm

    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        escalations = await conn.fetch("select * from escalations where run_id = $1", run_id)
    assert len(escalations) == 1
    assert escalations[0]["reason_code"] == "no_contact_email"


async def test_replay_is_idempotent_no_double_send(org_and_vendor, make_run):
    run_id = await make_run(state="renewal_due_soon", due_date=date.today())
    r1 = await send_first_outreach(org_and_vendor["org_id"], run_id)
    assert r1.state == RunState.awaiting_vendor_response

    # Replay: run has already left renewal_due_soon, so this must be a no-op,
    # not a second email / second counter bump.
    r2 = await send_first_outreach(org_and_vendor["org_id"], run_id)
    assert r2 is None

    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        run = await run_repo.get_run(conn, run_id)
        emails = await conn.fetch("select * from email_messages where run_id = $1", run_id)
    assert run.outreach_email_count == 1
    assert len(emails) == 1
