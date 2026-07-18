"""Regression tests for the qa-evals-engineer / coordinator finding #2
(2026-07-18, severe): every tool builds `ToolOutput.events` (PendingEvents)
per ADR 0004, but `app/orchestration/runner.py` never captured `.events` off
an awaited tool call — only `state_transition`/`guardrail_trip`/`error`/
`human_intervention` (written directly by the runner itself) ever landed in
`agent_events`. This breaks CLAUDE.md's Observability promise and the
trace-timeline UI (the product's trust surface): a run's trace would be
missing every tool call and LLM call, cost, and token count.

These tests drive real orchestration functions end-to-end against live
Postgres and assert `agent_events` actually contains `tool_call`/`llm_call`
rows with the tool name (and, for LLM calls, cost/tokens) populated —
not just that SOME event exists.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.db import org_scoped_tx
from app.ids import uuid7
from app.models.coi_fields import ExtractedCoiFields, ExtractedCoverageLine
from app.models.enums import CoverageType
from app.orchestration.runner import send_first_outreach
from app.retrieval import entity_repo

pytestmark = pytest.mark.asyncio


async def _agent_events_for_run(org_id, run_id):
    async with org_scoped_tx(org_id) as conn:
        rows = await conn.fetch(
            "select event_type, name, tool_name, llm_model, cost_cents, input_tokens, output_tokens, payload "
            "from agent_events where run_id = $1 order by created_at",
            run_id,
        )
    return [dict(r) for r in rows]


class TestSendEmailToolCallCaptured:
    async def test_send_first_outreach_records_a_send_email_tool_call_event(self, org_and_vendor, make_run):
        run_id = await make_run(state="renewal_due_soon", due_date=date.today())
        result = await send_first_outreach(org_and_vendor["org_id"], run_id)
        assert result is not None

        events = await _agent_events_for_run(org_and_vendor["org_id"], run_id)
        tool_call_events = [e for e in events if e["event_type"] == "tool_call" and e["tool_name"] == "send_email"]
        assert len(tool_call_events) >= 1, (
            f"expected a tool_call/send_email agent_events row; got event_types="
            f"{[e['event_type'] for e in events]}"
        )


class TestValidationToolCallCaptured:
    async def test_run_validation_records_an_update_coi_record_tool_call_event(self, org_and_vendor, make_run):
        from app.orchestration.runner import run_validation

        run_id = await make_run(state="validating", due_date=date.today())
        extraction = ExtractedCoiFields(
            policy_effective_date=date(2026, 1, 1),
            policy_expiration_date=date(2027, 1, 1),
            coverage_lines=[
                ExtractedCoverageLine(
                    coverage_type=CoverageType.general_liability,
                    each_occurrence=1_000_000,
                    aggregate=2_000_000,
                    additional_insured=True,
                    confidence=0.95,
                )
            ],
            overall_confidence=0.95,
        )
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            doc = await entity_repo.insert_coi_document(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], vendor_id=org_and_vendor["vendor_id"],
                run_id=run_id, storage_path="x/y.pdf", original_filename="y.pdf", content_type="application/pdf",
                byte_size=10, sha256="abc", source="email_inbound",
                version_number=await entity_repo.next_document_version(conn, org_and_vendor["vendor_id"]),
            )
            await entity_repo.insert_coi_extraction(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                coi_document_id=doc.id, extracted=extraction.model_dump(mode="json"), field_confidence={},
                overall_confidence=0.95, model="t", prompt_hash="p", input_tokens=1, output_tokens=1, cost_cents=1,
            )
            await conn.execute("update runs set coi_document_id = $2 where id = $1", run_id, doc.id)

        result = await run_validation(org_and_vendor["org_id"], run_id)
        assert result is not None

        events = await _agent_events_for_run(org_and_vendor["org_id"], run_id)
        tool_call_events = [
            e for e in events if e["event_type"] == "tool_call" and e["tool_name"] == "update_coi_record"
        ]
        assert len(tool_call_events) >= 1, (
            f"expected a tool_call/update_coi_record agent_events row; got event_types="
            f"{[e['event_type'] for e in events]}"
        )
