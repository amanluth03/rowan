"""Mirrors the ADR 0004 common tool envelope, used only where a test needs to
assert against a raw tool call/output shape rather than the higher-level
`RunTrajectory` (e.g. idempotency-replay and budget-denial assertions)."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ToolStatus(str, Enum):
    OK = "ok"
    DENIED = "denied"
    FAILED = "failed"


class BudgetSnapshot(BaseModel):
    outreach_count: int
    llm_calls_this_doc: int
    cost_cents_spent: int
    caps: dict[str, int]


class ToolContext(BaseModel):
    run_id: UUID
    organization_id: UUID
    idempotency_key: str
    budget_snapshot: BudgetSnapshot


class ToolOutput(BaseModel):
    status: ToolStatus
    idempotent_replay: bool = False
    events: list[dict[str, Any]] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    denial_reason: Optional[str] = None
