"""TDD: filed -> monitoring (the consequential, most-gated cascade), and
the human-triggered transitions out of needs_human_review / escalated_to_pm
/ errored (ADR 0002)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.db import org_scoped_tx
from app.ids import uuid7
from app.models.coi_fields import ExtractedCoiFields, ExtractedCoverageLine
from app.models.enums import CoverageType, RunState
from app.orchestration.runner import (
    complete_filing,
    recover_from_errored,
    resolve_escalated_to_pm,
    resolve_needs_human_review,
)
from app.retrieval import entity_repo, run_repo

pytestmark = pytest.mark.asyncio


def _clean_extraction(**overrides) -> ExtractedCoiFields:
    defaults = dict(
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
    defaults.update(overrides)
    return ExtractedCoiFields(**defaults)


async def _make_run_in_filed(org_and_vendor, make_run, *, result="pass", faithfulness_ok=True):
    run_id = await make_run(state="filed", due_date=date.today(), outreach_email_count=2, llm_call_count=3)
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        doc = await entity_repo.insert_coi_document(
            conn, id=uuid7(), organization_id=org_and_vendor["org_id"], vendor_id=org_and_vendor["vendor_id"],
            run_id=run_id, storage_path="x/y.pdf", original_filename="y.pdf", content_type="application/pdf",
            byte_size=10, sha256="abc", source="email_inbound",
            version_number=await entity_repo.next_document_version(conn, org_and_vendor["vendor_id"]),
        )
        ext = await entity_repo.insert_coi_extraction(
            conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
            coi_document_id=doc.id, extracted=_clean_extraction().model_dump(mode="json"),
            field_confidence={}, overall_confidence=0.95, model="t", prompt_hash="p",
            input_tokens=1, output_tokens=1, cost_cents=1,
        )
        validation = await entity_repo.insert_coi_validation(
            conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
            coi_extraction_id=ext.id, result=result, line_results=[], flags=[],
            faithfulness_ok=faithfulness_ok,
        )
        await conn.execute("update runs set coi_document_id = $2 where id = $1", run_id, doc.id)
    return run_id, doc, validation


class TestCompleteFiling:
    async def test_files_marks_complete_and_resets_for_next_cycle(self, org_and_vendor, make_run):
        run_id, doc, validation = await _make_run_in_filed(org_and_vendor, make_run)
        result = await complete_filing(
            org_and_vendor["org_id"], run_id, valid_from=date(2026, 1, 1), valid_to=date(2027, 1, 1)
        )
        assert result is not None
        assert result.state == RunState.monitoring
        assert result.outreach_email_count == 0
        assert result.llm_call_count == 0
        assert result.due_date == date(2027, 1, 1) - timedelta(days=30)

        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            filed_doc = await entity_repo.get_coi_document(conn, doc.id)
        assert filed_doc.is_current is True

    async def test_denied_when_validation_did_not_pass(self, org_and_vendor, make_run):
        run_id, doc, validation = await _make_run_in_filed(org_and_vendor, make_run, result="fail")
        result = await complete_filing(
            org_and_vendor["org_id"], run_id, valid_from=date(2026, 1, 1), valid_to=date(2027, 1, 1)
        )
        # mark_task_complete's hard precondition fails -> errored, per ADR 0004.
        assert result is not None
        assert result.state == RunState.errored

    async def test_replay_is_idempotent(self, org_and_vendor, make_run):
        run_id, doc, validation = await _make_run_in_filed(org_and_vendor, make_run)
        r1 = await complete_filing(
            org_and_vendor["org_id"], run_id, valid_from=date(2026, 1, 1), valid_to=date(2027, 1, 1)
        )
        assert r1.state == RunState.monitoring
        r2 = await complete_filing(
            org_and_vendor["org_id"], run_id, valid_from=date(2026, 1, 1), valid_to=date(2027, 1, 1)
        )
        assert r2 is None  # already left 'filed'; no-op, no double notify/complete


class TestNeedsHumanReviewDecisions:
    async def test_pm_approve_routes_to_filed(self, org_and_vendor, make_run):
        run_id, doc, validation = await _make_run_in_filed(
            org_and_vendor, make_run, result="fail", faithfulness_ok=True
        )
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            await run_repo.update_run_state(
                conn, run_id, from_state=RunState.filed, to_state=RunState.needs_human_review
            )
            esc = await entity_repo.insert_escalation(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                vendor_id=org_and_vendor["vendor_id"], kind="needs_human_review", reason_code="validation_failed",
                severity="warn", summary="test", details={"run_state": "needs_human_review"},
            )

        result = await resolve_needs_human_review(
            org_and_vendor["org_id"], run_id, decision="approve", escalation_id=esc.id, resolved_by=None
        )
        assert result is not None
        assert result.state == RunState.filed

    async def test_pm_reject_routes_to_escalated_to_pm(self, org_and_vendor, make_run):
        run_id, doc, validation = await _make_run_in_filed(org_and_vendor, make_run, result="fail")
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            await run_repo.update_run_state(
                conn, run_id, from_state=RunState.filed, to_state=RunState.needs_human_review
            )
            esc = await entity_repo.insert_escalation(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                vendor_id=org_and_vendor["vendor_id"], kind="needs_human_review", reason_code="validation_failed",
                severity="warn", summary="test", details={"run_state": "needs_human_review"},
            )

        result = await resolve_needs_human_review(
            org_and_vendor["org_id"], run_id, decision="reject", escalation_id=esc.id, resolved_by=None
        )
        assert result is not None
        assert result.state == RunState.escalated_to_pm

    async def test_pm_request_revision_routes_to_awaiting_vendor_response(self, org_and_vendor, make_run):
        run_id, doc, validation = await _make_run_in_filed(org_and_vendor, make_run, result="fail")
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            await run_repo.update_run_state(
                conn, run_id, from_state=RunState.filed, to_state=RunState.needs_human_review
            )
            esc = await entity_repo.insert_escalation(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                vendor_id=org_and_vendor["vendor_id"], kind="needs_human_review", reason_code="validation_failed",
                severity="warn", summary="test", details={"run_state": "needs_human_review"},
            )

        result = await resolve_needs_human_review(
            org_and_vendor["org_id"], run_id, decision="request_revision", escalation_id=esc.id, resolved_by=None
        )
        assert result is not None
        assert result.state == RunState.awaiting_vendor_response


class TestEscalatedToPmDecisions:
    async def test_resolved_routes_to_monitoring(self, org_and_vendor, make_run):
        run_id = await make_run(state="escalated_to_pm", due_date=date.today())
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            esc = await entity_repo.insert_escalation(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                vendor_id=org_and_vendor["vendor_id"], kind="escalated_to_pm", reason_code="no_response",
                severity="warn", summary="test", details={"run_state": "escalated_to_pm"},
            )
        result = await resolve_escalated_to_pm(
            org_and_vendor["org_id"], run_id, decision="resolved", escalation_id=esc.id, resolved_by=None
        )
        assert result is not None
        assert result.state == RunState.monitoring

    async def test_keep_chasing_routes_to_awaiting_vendor_response(self, org_and_vendor, make_run):
        run_id = await make_run(state="escalated_to_pm", due_date=date.today())
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            esc = await entity_repo.insert_escalation(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                vendor_id=org_and_vendor["vendor_id"], kind="escalated_to_pm", reason_code="no_response",
                severity="warn", summary="test", details={"run_state": "escalated_to_pm"},
            )
        result = await resolve_escalated_to_pm(
            org_and_vendor["org_id"], run_id, decision="keep_chasing", escalation_id=esc.id, resolved_by=None
        )
        assert result is not None
        assert result.state == RunState.awaiting_vendor_response


class TestErroredRecovery:
    async def test_human_recovery_returns_to_prior_state(self, org_and_vendor, make_run):
        run_id = await make_run(state="parsing", due_date=date.today())
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            await run_repo.update_run_state(conn, run_id, from_state=RunState.parsing, to_state=RunState.errored)
        result = await recover_from_errored(org_and_vendor["org_id"], run_id, to_state=RunState.parsing)
        assert result is not None
        assert result.state == RunState.parsing
