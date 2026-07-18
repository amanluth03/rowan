"""Tests for app/retrieval/run_repo.py — the compare-and-swap run-state
writer that makes state transitions crash-recoverable (see the module
docstring in run_repo.py for the full argument)."""

from __future__ import annotations

import pytest

from app.db import org_scoped_tx
from app.models.enums import RunState
from app.retrieval import run_repo

pytestmark = pytest.mark.asyncio


async def test_cas_transition_succeeds_from_matching_state(org_and_vendor, make_run):
    run_id = await make_run(state="monitoring")
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        updated = await run_repo.update_run_state(
            conn, run_id, from_state=RunState.monitoring, to_state=RunState.renewal_due_soon
        )
    assert updated is not None
    assert updated.state == RunState.renewal_due_soon


async def test_cas_transition_is_noop_when_state_already_moved(org_and_vendor, make_run):
    """Simulates replay after a crash: the run already left `from_state`
    (this same CAS already committed once) — a second attempt must not
    error and must not double-apply `extra` field updates."""
    run_id = await make_run(state="monitoring")

    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        first = await run_repo.update_run_state(
            conn, run_id, from_state=RunState.monitoring, to_state=RunState.renewal_due_soon
        )
    assert first is not None

    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        replay = await run_repo.update_run_state(
            conn, run_id, from_state=RunState.monitoring, to_state=RunState.renewal_due_soon
        )
    assert replay is None  # no-op: run is no longer in 'monitoring'

    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        current = await run_repo.get_run(conn, run_id)
    assert current.state == RunState.renewal_due_soon  # unchanged by the replay attempt


async def test_cas_transition_updates_extra_fields_atomically(org_and_vendor, make_run):
    run_id = await make_run(state="awaiting_vendor_response")
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        updated = await run_repo.update_run_state(
            conn,
            run_id,
            from_state=RunState.awaiting_vendor_response,
            to_state=RunState.document_received,
            extra={"coi_document_id": None},
        )
    assert updated is not None
    assert updated.state == RunState.document_received


async def test_update_run_state_rejects_disallowed_extra_column(org_and_vendor, make_run):
    run_id = await make_run(state="monitoring")
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        with pytest.raises(ValueError):
            await run_repo.update_run_state(
                conn,
                run_id,
                from_state=RunState.monitoring,
                to_state=RunState.renewal_due_soon,
                extra={"organization_id": "not-allowed"},
            )


async def test_increment_counters_is_additive(org_and_vendor, make_run):
    run_id = await make_run()
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        await run_repo.increment_counters(conn, run_id, outreach_delta=1, cost_cents_delta=5)
        await run_repo.increment_counters(conn, run_id, outreach_delta=1, cost_cents_delta=7)
        run = await run_repo.get_run(conn, run_id)
    assert run.outreach_email_count == 2
    assert run.cost_cents_spent == 12


async def test_active_run_partial_unique_prevents_two_active_runs_per_vendor(org_and_vendor, make_run, admin_conn):
    await make_run(status="active")
    with pytest.raises(Exception):
        await admin_conn.execute(
            """
            insert into runs (id, organization_id, vendor_id, state, status, trigger, reply_token)
            values (gen_random_uuid(), $1, $2, 'monitoring', 'active', 'renewal_due', $3)
            """,
            org_and_vendor["org_id"], org_and_vendor["vendor_id"], f"tok-{org_and_vendor['org_id']}-2",
        )
