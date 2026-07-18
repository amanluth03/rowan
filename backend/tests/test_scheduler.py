"""TDD: the scheduler sweep — org enumeration via rowan_system, then
per-org run scanning (ADR 0002's [scheduler]-triggered transitions)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.db import org_scoped_tx
from app.models.enums import RunState
from app.orchestration.scheduler import scheduler_tick
from app.retrieval import run_repo

pytestmark = pytest.mark.asyncio


async def test_sweep_advances_monitoring_run_past_lead_window(org_and_vendor, make_run):
    run_id = await make_run(state="monitoring", due_date=date.today() + timedelta(days=5))
    stats = await scheduler_tick(now=date.today())
    assert stats["runs_advanced"] >= 1

    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        run = await run_repo.get_run(conn, run_id)
    assert run.state == RunState.renewal_due_soon


async def test_sweep_skips_disabled_orgs(org_and_vendor, make_run, admin_conn):
    await admin_conn.execute(
        "update organizations set agent_enabled = false where id = $1", org_and_vendor["org_id"]
    )
    run_id = await make_run(state="monitoring", due_date=date.today() + timedelta(days=5))
    await scheduler_tick(now=date.today())

    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        run = await run_repo.get_run(conn, run_id)
    assert run.state == RunState.monitoring  # untouched


async def test_sweep_does_not_touch_unrelated_run_far_from_due(org_and_vendor, make_run):
    run_id = await make_run(state="monitoring", due_date=date.today() + timedelta(days=90))
    await scheduler_tick(now=date.today())

    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        run = await run_repo.get_run(conn, run_id)
    assert run.state == RunState.monitoring
