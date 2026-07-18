"""Cron/scheduler triggers (backend-engineer scope): renewal-due scanning
and follow-up scheduling within budget. Intended to be invoked periodically
(e.g. a Vercel cron hitting a `/internal/scheduler/tick` route, or a
standalone worker loop) — this module contains the sweep logic itself,
independent of however it gets invoked.

RLS note (ADR 0001): org enumeration uses the narrow `rowan_system` role
(reads `organizations.id where agent_enabled`); once an org is known, every
per-run action goes through the normal `rowan_app`-backed, GUC-scoped path
via app.orchestration.runner's functions — "the scheduler iterates orgs and
sets the GUC per org."
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from app.db import system_conn
from app.models.enums import RunState
from app.orchestration import runner
from app.retrieval import run_repo
from app.db import org_scoped_tx


async def _enumerate_enabled_org_ids() -> list[Any]:
    async with system_conn() as conn:
        rows = await conn.fetch("select id from organizations where agent_enabled")
    return [r["id"] for r in rows]


async def scheduler_tick(*, now: date | None = None, now_dt: datetime | None = None) -> dict[str, int]:
    """One sweep across every enabled org. Safe to call repeatedly / on an
    overlapping schedule: every underlying transition is itself idempotent
    (CAS + tool_invocations), so a duplicate tick just re-evaluates guards
    that, in the common case, no longer hold.
    """
    now = now or date.today()
    now_dt = now_dt or datetime.now(timezone.utc)
    stats = {"orgs_scanned": 0, "runs_advanced": 0, "runs_escalated": 0}

    org_ids = await _enumerate_enabled_org_ids()
    for org_id in org_ids:
        stats["orgs_scanned"] += 1

        async with org_scoped_tx(org_id) as conn:
            monitoring_runs = await run_repo.list_runs_in_state(conn, RunState.monitoring)
            renewal_due_runs = await run_repo.list_runs_in_state(conn, RunState.renewal_due_soon)
            awaiting_wakeups = await run_repo.list_runs_awaiting_wakeup(conn, now=now_dt)
            document_received_runs = await run_repo.list_runs_in_state(conn, RunState.document_received)

        for run in monitoring_runs:
            result = await runner.evaluate_expiry(org_id, run.id, now=now)
            if result is not None:
                stats["runs_advanced"] += 1

        for run in renewal_due_runs:
            result = await runner.send_first_outreach(org_id, run.id, now=now_dt)
            if result is not None:
                stats["runs_advanced"] += 1
                if result.state == RunState.escalated_to_pm:
                    stats["runs_escalated"] += 1

        for run in awaiting_wakeups:
            if run.state != RunState.awaiting_vendor_response:
                continue  # wakeup list is a hint; guard functions re-check state
            result = await runner.check_followup_or_deadline(org_id, run.id, now=now_dt)
            if result is not None:
                stats["runs_advanced"] += 1
                if result.state == RunState.escalated_to_pm:
                    stats["runs_escalated"] += 1

        # Crash-recovery sweep: a run stuck in document_received (process
        # died between storing the attachment and cascading to parsing)
        # gets a chance to resume here, not just on the next fresh webhook.
        for run in document_received_runs:
            result = await runner.advance_from_document_received(org_id, run.id)
            if result is not None:
                stats["runs_advanced"] += 1

    return stats
