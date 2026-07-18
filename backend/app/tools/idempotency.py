"""The shared `tool_invocations` idempotency mechanism backing every tool
(ADR 0004). Two-phase, because a tool's side effect is often an external
call (Resend, Claude API) that must not happen inside a long-held DB
transaction:

  1. `reserve()` — a short transaction that does
     `INSERT ... ON CONFLICT (tool_name, idempotency_key) DO NOTHING`.
     - Row inserted -> caller owns this invocation; go perform the side
       effect.
     - Row already existed with status `succeeded` or `failed` -> terminal;
       return the stored response as a replay, perform NO side effect.
     - Row already existed with status `pending` and its lease hasn't
       expired -> another caller is actively working on it (or this is a
       true concurrent double-call); deny, no side effect.
     - Row already existed with status `pending` but its lease HAS expired
       (a process crashed mid-side-effect) -> take over the lease (bump
       `created_at`) and retry the side effect. This is the crash-recovery
       path: a crash between `reserve()` committing and `complete()`
       committing leaves a `pending` row, and the next attempt (same
       idempotency key, from the scheduler/webhook retry) resumes it rather
       than either double-firing or wedging forever.
  2. `complete()` — a second transaction, run AFTER the side effect returns,
     that writes the terminal status + response/error. Callers bundle this
     in the SAME transaction as any entity writes and the `agent_events`
     insert for that tool call, so "the tool succeeded" and "its effects are
     visible" commit atomically together.

# ASSUMPTION: a 120s pending-lease timeout for takeover is a placeholder;
tune against real Resend/Claude latency once observed in prod. Chosen to be
comfortably above every tool's documented timeout (10s/60s/5s/10s) so a
still-in-flight call is never preempted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg

from app.ids import uuid7

STALE_PENDING_LEASE_SECONDS = 120


@dataclass
class IdempotencyOutcome:
    invocation_id: UUID
    proceed: bool  # True -> caller must perform the side effect now
    replay: bool  # True -> stored_response is a prior result, no side effect happened this call
    stored_response: dict[str, Any] | None = None
    stored_error: dict[str, Any] | None = None
    stored_status: str | None = None


async def reserve(
    conn: asyncpg.Connection,
    *,
    organization_id: UUID,
    run_id: UUID | None,
    tool_name: str,
    idempotency_key: str,
    request_hash: str,
) -> IdempotencyOutcome:
    inserted = await conn.fetchrow(
        """
        insert into tool_invocations (
            id, organization_id, run_id, tool_name, idempotency_key, request_hash, status
        ) values ($1,$2,$3,$4,$5,$6,'pending')
        on conflict (tool_name, idempotency_key) do nothing
        returning id
        """,
        uuid7(), organization_id, run_id, tool_name, idempotency_key, request_hash,
    )
    if inserted is not None:
        return IdempotencyOutcome(invocation_id=inserted["id"], proceed=True, replay=False)

    existing = await conn.fetchrow(
        """
        select id, status, response, error, created_at,
               (extract(epoch from (now() - created_at)) > $3) as lease_expired
        from tool_invocations
        where tool_name = $1 and idempotency_key = $2
        for update
        """,
        tool_name, idempotency_key, STALE_PENDING_LEASE_SECONDS,
    )
    assert existing is not None  # conflict implies a row exists

    if existing["status"] in ("succeeded", "failed"):
        return IdempotencyOutcome(
            invocation_id=existing["id"],
            proceed=False,
            replay=True,
            stored_response=_loads(existing["response"]),
            stored_error=_loads(existing["error"]),
            stored_status=existing["status"],
        )

    # status == 'pending'
    if existing["lease_expired"]:
        await conn.execute(
            "update tool_invocations set created_at = now(), request_hash = $2 where id = $1",
            existing["id"], request_hash,
        )
        return IdempotencyOutcome(invocation_id=existing["id"], proceed=True, replay=False)

    # Someone else is actively working on this exact logical action right now.
    return IdempotencyOutcome(
        invocation_id=existing["id"],
        proceed=False,
        replay=False,
        stored_status="pending",
    )


async def complete(
    conn: asyncpg.Connection,
    invocation_id: UUID,
    *,
    status: str,
    response: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    await conn.execute(
        """
        update tool_invocations
        set status = $2, response = $3, error = $4, completed_at = now()
        where id = $1
        """,
        invocation_id, status, json.dumps(response) if response is not None else None,
        json.dumps(error) if error is not None else None,
    )


def _loads(value: Any) -> Any:
    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    return value
