"""Tests for the shared tool_invocations idempotency mechanism
(app/tools/idempotency.py) — the single most important correctness property
in this build per CLAUDE.md: "every write path assumes it can be called
twice... must not double-send or double-file."
"""

from __future__ import annotations

import asyncio

import pytest

from app.db import org_scoped_tx
from app.tools import idempotency

pytestmark = pytest.mark.asyncio


async def test_first_reserve_proceeds(org_and_vendor):
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        outcome = await idempotency.reserve(
            conn,
            organization_id=org_and_vendor["org_id"],
            run_id=None,
            tool_name="test_tool",
            idempotency_key=f"key-1-{org_and_vendor['org_id']}",
            request_hash="hash-1",
        )
    assert outcome.proceed is True
    assert outcome.replay is False


async def test_second_reserve_before_complete_is_denied_in_progress(org_and_vendor):
    key = f"key-in-progress-{org_and_vendor['org_id']}"
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        first = await idempotency.reserve(
            conn,
            organization_id=org_and_vendor["org_id"],
            run_id=None,
            tool_name="test_tool",
            idempotency_key=key,
            request_hash="hash",
        )
    assert first.proceed is True

    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        second = await idempotency.reserve(
            conn,
            organization_id=org_and_vendor["org_id"],
            run_id=None,
            tool_name="test_tool",
            idempotency_key=key,
            request_hash="hash",
        )
    assert second.proceed is False
    assert second.replay is False
    assert second.stored_status == "pending"


async def test_replay_after_success_returns_stored_response_with_no_new_side_effect(org_and_vendor):
    key = f"key-success-{org_and_vendor['org_id']}"
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        first = await idempotency.reserve(
            conn,
            organization_id=org_and_vendor["org_id"],
            run_id=None,
            tool_name="test_tool",
            idempotency_key=key,
            request_hash="hash",
        )
        await idempotency.complete(
            conn, first.invocation_id, status="succeeded", response={"provider_message_id": "abc123"}
        )

    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        replay = await idempotency.reserve(
            conn,
            organization_id=org_and_vendor["org_id"],
            run_id=None,
            tool_name="test_tool",
            idempotency_key=key,
            request_hash="hash",
        )
    assert replay.proceed is False
    assert replay.replay is True
    assert replay.stored_status == "succeeded"
    assert replay.stored_response == {"provider_message_id": "abc123"}


async def test_stale_pending_lease_can_be_taken_over(org_and_vendor, monkeypatch):
    """Simulates a crash: a 'pending' row older than the lease timeout must
    be resumable by a later retry, not wedged forever."""
    monkeypatch.setattr(idempotency, "STALE_PENDING_LEASE_SECONDS", 0)
    key = f"key-crash-{org_and_vendor['org_id']}"

    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        first = await idempotency.reserve(
            conn,
            organization_id=org_and_vendor["org_id"],
            run_id=None,
            tool_name="test_tool",
            idempotency_key=key,
            request_hash="hash",
        )
    assert first.proceed is True
    # Never call complete() -- simulates a crash mid-side-effect.

    await asyncio.sleep(1.1)  # exceed the (patched-to-0) lease window comfortably

    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        retry = await idempotency.reserve(
            conn,
            organization_id=org_and_vendor["org_id"],
            run_id=None,
            tool_name="test_tool",
            idempotency_key=key,
            request_hash="hash",
        )
    assert retry.proceed is True
    assert retry.invocation_id == first.invocation_id


async def test_different_keys_do_not_collide(org_and_vendor):
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        a = await idempotency.reserve(
            conn, organization_id=org_and_vendor["org_id"], run_id=None,
            tool_name="test_tool", idempotency_key=f"a-{org_and_vendor['org_id']}", request_hash="h",
        )
        b = await idempotency.reserve(
            conn, organization_id=org_and_vendor["org_id"], run_id=None,
            tool_name="test_tool", idempotency_key=f"b-{org_and_vendor['org_id']}", request_hash="h",
        )
    assert a.proceed and b.proceed
    assert a.invocation_id != b.invocation_id
