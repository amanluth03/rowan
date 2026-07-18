"""Run state (tier a) repository — the ONLY place `runs` rows are written.

Crash-recoverability contract (backend-engineer's core obligation on this
task): `update_run_state` is a compare-and-swap UPDATE keyed on
`(id, state=from_state)`. If a process crashes after committing this
statement but before the caller does anything else, the transition already
happened — durably, in Postgres, in one statement — so recovery is just "the
next scheduler tick / webhook / tool callback re-reads run.state and resumes
from wherever it actually is." If a process crashes *before* this statement
commits, nothing happened — the run is still in `from_state` and the same
trigger will re-evaluate the same guard next time. There is no "half
transitioned" state representable in this schema: `runs.state` is a single
column written by a single UPDATE per transition, and `agent_events` is
written in the SAME transaction (`app/orchestration/runner.py`), so a
transition and its trace record can never diverge.

A CAS that matches zero rows is NOT an error — it means the run already left
`from_state` (a concurrent tick beat us to it, or we're replaying after a
crash that actually did commit). Callers treat that as "no-op, re-read
current state," never as a fatal condition. This is what makes scheduler
ticks and webhook replays idempotent against the state machine itself, on
top of the `tool_invocations` idempotency ledger that makes tool side
effects idempotent.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

import asyncpg

from app.ids import uuid7
from app.models.enums import RunState, RunStatus
from app.retrieval.models import RunRow

# Columns `update_run_state` is allowed to touch via `extra`, beyond
# state/status. A fixed allowlist (not arbitrary **kwargs -> SQL) so this
# function can never be used to write an arbitrary column from caller input.
_UPDATABLE_EXTRA_COLUMNS = {
    "coi_document_id",
    "due_date",
    "next_action_at",
    "outreach_email_count",
    "llm_call_count",
    "cost_cents_spent",
    "reply_token",
    "reply_token_expires_at",
    "paused_by",
    "completed_at",
}

_SELECT_COLUMNS = """
    id, organization_id, vendor_id, coi_document_id, state, status, trigger, due_date,
    next_action_at, outreach_email_count, llm_call_count, cost_cents_spent,
    budget_cost_cap_cents, reply_token, reply_token_expires_at, paused_by,
    started_at, updated_at, completed_at
"""


def _row(r: asyncpg.Record) -> RunRow:
    return RunRow(**dict(r))


async def create_run(
    conn: asyncpg.Connection,
    *,
    organization_id: UUID,
    vendor_id: UUID,
    trigger: str,
    due_date: date | None,
    budget_cost_cap_cents: int,
    reply_token: str,
    reply_token_expires_at: datetime,
) -> RunRow:
    row = await conn.fetchrow(
        f"""
        insert into runs (
            id, organization_id, vendor_id, trigger, due_date, budget_cost_cap_cents,
            reply_token, reply_token_expires_at
        ) values ($1,$2,$3,$4,$5,$6,$7,$8)
        returning {_SELECT_COLUMNS}
        """,
        uuid7(), organization_id, vendor_id, trigger, due_date, budget_cost_cap_cents,
        reply_token, reply_token_expires_at,
    )
    return _row(row)


async def get_run(conn: asyncpg.Connection, run_id: UUID) -> RunRow | None:
    row = await conn.fetchrow(f"select {_SELECT_COLUMNS} from runs where id = $1", run_id)
    return _row(row) if row else None


async def get_run_for_update(conn: asyncpg.Connection, run_id: UUID) -> RunRow | None:
    """SELECT ... FOR UPDATE — used when the caller needs to read-then-write
    within one transaction and must prevent a concurrent scheduler/webhook
    tick from doing the same (e.g. incrementing outreach_email_count)."""
    row = await conn.fetchrow(f"select {_SELECT_COLUMNS} from runs where id = $1 for update", run_id)
    return _row(row) if row else None


async def get_active_run_for_vendor(conn: asyncpg.Connection, vendor_id: UUID) -> RunRow | None:
    row = await conn.fetchrow(
        f"select {_SELECT_COLUMNS} from runs where vendor_id = $1 and status = 'active'",
        vendor_id,
    )
    return _row(row) if row else None


async def get_run_by_reply_token(conn: asyncpg.Connection, reply_token: str) -> RunRow | None:
    row = await conn.fetchrow(
        f"select {_SELECT_COLUMNS} from runs where reply_token = $1", reply_token
    )
    return _row(row) if row else None


async def list_runs_in_state(
    conn: asyncpg.Connection, state: RunState, *, only_active: bool = True
) -> list[RunRow]:
    if only_active:
        rows = await conn.fetch(
            f"select {_SELECT_COLUMNS} from runs where state = $1 and status = 'active'",
            state.value,
        )
    else:
        rows = await conn.fetch(f"select {_SELECT_COLUMNS} from runs where state = $1", state.value)
    return [_row(r) for r in rows]


async def list_runs_awaiting_wakeup(conn: asyncpg.Connection, *, now: datetime) -> list[RunRow]:
    """Runs whose scheduled wakeup has arrived (follow-up / deadline checks
    in `awaiting_vendor_response`)."""
    rows = await conn.fetch(
        f"""
        select {_SELECT_COLUMNS} from runs
        where status = 'active' and next_action_at is not null and next_action_at <= $1
        """,
        now,
    )
    return [_row(r) for r in rows]


async def update_run_state(
    conn: asyncpg.Connection,
    run_id: UUID,
    *,
    from_state: RunState,
    to_state: RunState,
    status: RunStatus | None = None,
    extra: dict[str, Any] | None = None,
) -> RunRow | None:
    """Atomic CAS transition. Returns the updated row, or None if the run
    was not in `from_state` at execution time (no-op; caller re-reads).
    """
    extra = extra or {}
    unknown = set(extra) - _UPDATABLE_EXTRA_COLUMNS
    if unknown:
        raise ValueError(f"update_run_state: disallowed columns in extra: {unknown}")

    set_clauses = ["state = $3", "updated_at = now()"]
    params: list[Any] = [run_id, from_state.value, to_state.value]
    next_param = 4

    if status is not None:
        set_clauses.append(f"status = ${next_param}")
        params.append(status.value)
        next_param += 1

    for col, val in extra.items():
        set_clauses.append(f"{col} = ${next_param}")
        params.append(val)
        next_param += 1

    sql = f"""
        update runs set {", ".join(set_clauses)}
        where id = $1 and state = $2
        returning {_SELECT_COLUMNS}
    """
    row = await conn.fetchrow(sql, *params)
    return _row(row) if row else None


async def increment_counters(
    conn: asyncpg.Connection,
    run_id: UUID,
    *,
    outreach_delta: int = 0,
    llm_call_delta: int = 0,
    cost_cents_delta: int = 0,
) -> RunRow:
    """Atomic increment, used inside a tool's own transaction right after a
    side effect succeeds (e.g. send_email bumping outreach_email_count).
    Increments are relative (`col = col + $n`), so two racing callers each
    still see a correct final sum even without an external lock — combined
    with the tool_invocations idempotency key, a retried call never
    increments twice for the same logical send.
    """
    row = await conn.fetchrow(
        f"""
        update runs
        set outreach_email_count = outreach_email_count + $2,
            llm_call_count = llm_call_count + $3,
            cost_cents_spent = cost_cents_spent + $4,
            updated_at = now()
        where id = $1
        returning {_SELECT_COLUMNS}
        """,
        run_id, outreach_delta, llm_call_delta, cost_cents_delta,
    )
    return _row(row)


async def set_run_status(
    conn: asyncpg.Connection, run_id: UUID, status: RunStatus, *, paused_by: UUID | None = None
) -> RunRow:
    row = await conn.fetchrow(
        f"""
        update runs set status = $2, paused_by = $3, updated_at = now()
        where id = $1
        returning {_SELECT_COLUMNS}
        """,
        run_id, status.value, paused_by,
    )
    return _row(row)
