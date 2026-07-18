"""agent_events writer (layer 6). Append-only, one-way: "All layers ->
Observability: append-only AgentEvent structs... Observability returns
nothing that changes control flow" (ADR 0003). Never UPDATEd (ADR 0001
`# ASSUMPTION`); corrections are new rows.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

from app.ids import uuid7
from app.models.enums import EventSeverity, EventType, RunState


async def write_event(
    conn: asyncpg.Connection,
    *,
    organization_id: UUID,
    event_type: EventType,
    name: str,
    run_id: UUID | None = None,
    vendor_id: UUID | None = None,
    severity: EventSeverity = EventSeverity.info,
    from_state: RunState | None = None,
    to_state: RunState | None = None,
    tool_name: str | None = None,
    idempotency_key: str | None = None,
    llm_model: str | None = None,
    prompt_hash: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_cents: int | None = None,
    latency_ms: int | None = None,
    payload: dict[str, Any] | None = None,
) -> UUID:
    import json

    event_id = uuid7()
    await conn.execute(
        """
        insert into agent_events (
            id, organization_id, run_id, vendor_id, event_type, name, severity,
            from_state, to_state, tool_name, idempotency_key, llm_model, prompt_hash,
            input_tokens, output_tokens, cost_cents, latency_ms, payload
        ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
        """,
        event_id, organization_id, run_id, vendor_id, event_type.value, name, severity.value,
        from_state.value if from_state else None,
        to_state.value if to_state else None,
        tool_name, idempotency_key, llm_model, prompt_hash,
        input_tokens, output_tokens, cost_cents, latency_ms,
        json.dumps(payload or {}),
    )
    return event_id
