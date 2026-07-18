"""Integration tests for the tools layer against a live Postgres, covering
idempotent replay for each write-action tool and mark_task_complete's hard
precondition (ADR 0004 #6 — the most-gated tool).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.db import org_scoped_tx
from app.ids import uuid7
from app.models.coi_fields import ExtractedCoiFields, ExtractedCoverageLine
from app.models.enums import CoverageType, ToolStatus
from app.models.tool_contracts import BudgetSnapshot, ToolContext
from app.retrieval import entity_repo
from app.tools.file_document import FileDocumentInput, file_document
from app.tools.mark_task_complete import MarkTaskCompleteInput, mark_task_complete
from app.tools.send_email import SendEmailInput, send_email
from app.tools.update_coi_record import UpdateCoiRecordWriteInput, read_coi_record, write_coi_record

pytestmark = pytest.mark.asyncio


def _budget(**overrides):
    defaults = dict(
        outreach_email_count=0, llm_calls_this_doc=0, cost_cents_spent=0,
        max_outreach=3, max_llm_per_doc=5, budget_cost_cap_cents=200,
    )
    defaults.update(overrides)
    return BudgetSnapshot(**defaults)


def _context(run_id, org_id, key="k") -> ToolContext:
    return ToolContext(run_id=run_id, organization_id=org_id, idempotency_key=key, budget=_budget())


async def _insert_document(org_id, vendor_id, run_id=None):
    async with org_scoped_tx(org_id) as conn:
        doc = await entity_repo.insert_coi_document(
            conn,
            id=uuid7(),
            organization_id=org_id,
            vendor_id=vendor_id,
            run_id=run_id,
            storage_path=f"{vendor_id}/test.pdf",
            original_filename="test.pdf",
            content_type="application/pdf",
            byte_size=100,
            sha256="deadbeef",
            source="email_inbound",
            version_number=await entity_repo.next_document_version(conn, vendor_id),
        )
    return doc


class TestReadUpdateCoiRecord:
    async def test_read_returns_requirements_and_history(self, org_and_vendor, make_run):
        run_id = await make_run()
        doc = await _insert_document(org_and_vendor["org_id"], org_and_vendor["vendor_id"], run_id)
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            result = await read_coi_record(conn, vendor_id=org_and_vendor["vendor_id"])
        assert result.status == ToolStatus.ok
        assert len(result.data.requirements) == 1
        assert result.data.requirements[0].coverage_type == CoverageType.general_liability
        assert any(d.id == doc.id for d in result.data.history)


class TestWriteUpdateCoiRecord:
    async def test_clean_extraction_passes_and_is_idempotent(self, org_and_vendor, make_run):
        run_id = await make_run()
        doc = await _insert_document(org_and_vendor["org_id"], org_and_vendor["vendor_id"], run_id)

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
            ext_row = await entity_repo.insert_coi_extraction(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                coi_document_id=doc.id, extracted=extraction.model_dump(mode="json"),
                field_confidence={}, overall_confidence=0.95, model="test", prompt_hash="ph",
                input_tokens=1, output_tokens=1, cost_cents=1,
            )

        ctx = _context(run_id, org_and_vendor["org_id"], key=f"validate-{run_id}")
        write_input = UpdateCoiRecordWriteInput(coi_extraction_id=ext_row.id, confidence_threshold=0.8)

        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            result = await write_coi_record(conn, ctx, write_input)
        assert result.status == ToolStatus.ok
        assert result.data.result == "pass"
        assert result.data.faithfulness_ok is True

        # Replay with the same idempotency key -> no new coi_validations row.
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            replay = await write_coi_record(conn, ctx, write_input)
        assert replay.idempotent_replay is True
        assert replay.data.validation_id == result.data.validation_id

    async def test_explicit_as_of_is_honored_not_wall_clock(self, org_and_vendor, make_run):
        """Regression test (qa-evals-engineer finding #4, 2026-07-18):
        write_coi_record must use a caller-supplied `as_of`, not silently
        default to real wall-clock `date.today()` — otherwise "is this
        policy expired/not-yet-effective" drifts with real time instead of
        being pinned to the run's/fixture's frozen `now`.

        Construct an extraction whose `policy_expiration_date` is in the
        future relative to REAL today (so it would incorrectly PASS if
        as_of were ignored), but in the PAST relative to an explicit,
        far-future `as_of` we pass in (so it must FAIL if as_of is actually
        honored).
        """
        run_id = await make_run()
        doc = await _insert_document(org_and_vendor["org_id"], org_and_vendor["vendor_id"], run_id)

        real_today = date.today()
        frozen_future_as_of = real_today + timedelta(days=365)

        extraction = ExtractedCoiFields(
            policy_effective_date=real_today - timedelta(days=30),
            policy_expiration_date=real_today + timedelta(days=10),  # valid vs. real today
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
            ext_row = await entity_repo.insert_coi_extraction(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                coi_document_id=doc.id, extracted=extraction.model_dump(mode="json"),
                field_confidence={}, overall_confidence=0.95, model="test", prompt_hash="ph",
                input_tokens=1, output_tokens=1, cost_cents=1,
            )

        ctx = _context(run_id, org_and_vendor["org_id"], key=f"validate-asof-{run_id}")
        write_input = UpdateCoiRecordWriteInput(
            coi_extraction_id=ext_row.id, confidence_threshold=0.8, as_of=frozen_future_as_of
        )

        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            result = await write_coi_record(conn, ctx, write_input)

        assert result.status == ToolStatus.ok
        assert result.data.result == "fail", "as_of was not honored — validation used wall-clock today instead"
        assert any(f.get("code") == "policy_expired" for f in result.data.flags)


class TestFileDocument:
    async def test_files_and_supersedes(self, org_and_vendor, make_run):
        run_id = await make_run()
        doc1 = await _insert_document(org_and_vendor["org_id"], org_and_vendor["vendor_id"], run_id)
        ctx = _context(run_id, org_and_vendor["org_id"])

        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            r1 = await file_document(
                conn, ctx,
                FileDocumentInput(coi_document_id=doc1.id, valid_from=date(2026, 1, 1), valid_to=date(2027, 1, 1)),
            )
        assert r1.status == ToolStatus.ok
        assert r1.data.is_current is True
        assert r1.data.superseded_document_id is None

        doc2 = await _insert_document(org_and_vendor["org_id"], org_and_vendor["vendor_id"], run_id)
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            r2 = await file_document(
                conn, ctx,
                FileDocumentInput(coi_document_id=doc2.id, valid_from=date(2027, 1, 1), valid_to=date(2028, 1, 1)),
            )
        assert r2.data.superseded_document_id == doc1.id

        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            old = await entity_repo.get_coi_document(conn, doc1.id)
        assert old.is_current is False
        assert old.status.value == "superseded"

    async def test_filing_same_document_twice_is_idempotent(self, org_and_vendor, make_run):
        run_id = await make_run()
        doc = await _insert_document(org_and_vendor["org_id"], org_and_vendor["vendor_id"], run_id)
        ctx = _context(run_id, org_and_vendor["org_id"])
        input_ = FileDocumentInput(coi_document_id=doc.id, valid_from=date(2026, 1, 1), valid_to=date(2027, 1, 1))

        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            r1 = await file_document(conn, ctx, input_)
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            r2 = await file_document(conn, ctx, input_)

        assert r1.status == ToolStatus.ok
        assert r2.idempotent_replay is True
        assert r2.data.coi_document_id == doc.id


class TestMarkTaskComplete:
    async def test_denied_when_validation_failed(self, org_and_vendor, make_run):
        run_id = await make_run()
        doc = await _insert_document(org_and_vendor["org_id"], org_and_vendor["vendor_id"], run_id)
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            ext = await entity_repo.insert_coi_extraction(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                coi_document_id=doc.id, extracted={}, field_confidence={}, overall_confidence=0.5,
                model="t", prompt_hash="p", input_tokens=1, output_tokens=1, cost_cents=1,
            )
            validation = await entity_repo.insert_coi_validation(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                coi_extraction_id=ext.id, result="fail", line_results=[], flags=[], faithfulness_ok=True,
            )

        ctx = _context(run_id, org_and_vendor["org_id"])
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            result = await mark_task_complete(
                conn, ctx,
                MarkTaskCompleteInput(
                    coi_validation_id=validation.id, completion_basis="validation_passed", renewal_lead_days=30
                ),
            )
        assert result.status == ToolStatus.denied
        assert result.guardrail_name == "mark_task_complete_precondition_failed"

    async def test_allowed_when_validation_passed_and_faithful(self, org_and_vendor, make_run):
        run_id = await make_run()
        doc = await _insert_document(org_and_vendor["org_id"], org_and_vendor["vendor_id"], run_id)
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            await entity_repo.file_coi_document(
                conn, coi_document_id=doc.id, valid_from=date(2026, 1, 1), valid_to=date(2027, 1, 1)
            )
            ext = await entity_repo.insert_coi_extraction(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                coi_document_id=doc.id, extracted={}, field_confidence={}, overall_confidence=0.95,
                model="t", prompt_hash="p", input_tokens=1, output_tokens=1, cost_cents=1,
            )
            validation = await entity_repo.insert_coi_validation(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                coi_extraction_id=ext.id, result="pass", line_results=[], flags=[], faithfulness_ok=True,
            )

        ctx = _context(run_id, org_and_vendor["org_id"])
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            result = await mark_task_complete(
                conn, ctx,
                MarkTaskCompleteInput(
                    coi_validation_id=validation.id, completion_basis="validation_passed", renewal_lead_days=30
                ),
            )
        assert result.status == ToolStatus.ok
        assert result.data.next_due_date == date(2027, 1, 1) - timedelta(days=30)

    async def test_denied_when_basis_is_human_approved_but_no_approval_exists(self, org_and_vendor, make_run):
        run_id = await make_run()
        doc = await _insert_document(org_and_vendor["org_id"], org_and_vendor["vendor_id"], run_id)
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            ext = await entity_repo.insert_coi_extraction(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                coi_document_id=doc.id, extracted={}, field_confidence={}, overall_confidence=0.5,
                model="t", prompt_hash="p", input_tokens=1, output_tokens=1, cost_cents=1,
            )
            validation = await entity_repo.insert_coi_validation(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                coi_extraction_id=ext.id, result="fail", line_results=[], flags=[], faithfulness_ok=True,
            )

        ctx = _context(run_id, org_and_vendor["org_id"])
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            result = await mark_task_complete(
                conn, ctx,
                MarkTaskCompleteInput(
                    coi_validation_id=validation.id, completion_basis="human_approved", renewal_lead_days=30
                ),
            )
        assert result.status == ToolStatus.denied


class TestSendEmail:
    async def test_send_succeeds_and_increments_outreach_counter(self, org_and_vendor, make_run):
        run_id = await make_run()
        ctx = _context(run_id, org_and_vendor["org_id"])
        result = await send_email(
            ctx,
            SendEmailInput(
                to_email="vendor@example.com", from_email="rowan@example.com",
                template_id="first_outreach", template_vars={"vendor_name": "Test Vendor"},
                vendor_id=org_and_vendor["vendor_id"], sequence=0,
            ),
        )
        assert result.status == ToolStatus.ok
        assert result.data.delivery_status == "sent"

        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            run = await conn.fetchrow("select outreach_email_count from runs where id = $1", run_id)
        assert run["outreach_email_count"] == 1

    async def test_replay_does_not_double_increment_counter(self, org_and_vendor, make_run):
        run_id = await make_run()
        ctx = _context(run_id, org_and_vendor["org_id"])
        input_ = SendEmailInput(
            to_email="vendor@example.com", from_email="rowan@example.com",
            template_id="first_outreach", template_vars={"vendor_name": "Test Vendor"},
            vendor_id=org_and_vendor["vendor_id"], sequence=0,
        )
        r1 = await send_email(ctx, input_)
        r2 = await send_email(ctx, input_)
        assert r1.status == ToolStatus.ok
        assert r2.idempotent_replay is True

        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            run = await conn.fetchrow("select outreach_email_count from runs where id = $1", run_id)
        assert run["outreach_email_count"] == 1  # NOT 2

    async def test_pm_notice_does_not_increment_outreach_counter(self, org_and_vendor, make_run):
        run_id = await make_run()
        ctx = _context(run_id, org_and_vendor["org_id"])
        await send_email(
            ctx,
            SendEmailInput(
                to_email="pm@example.com", from_email="rowan@example.com",
                template_id="handled_notice", template_vars={"vendor_name": "Test Vendor"},
                sequence="cycle-1",
            ),
        )
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            run = await conn.fetchrow("select outreach_email_count from runs where id = $1", run_id)
        assert run["outreach_email_count"] == 0

    async def test_transport_is_injectable(self, org_and_vendor, make_run):
        """Regression test for qa-evals-engineer finding #5 (2026-07-18,
        low priority): send_email always called the real resend_client.send
        directly, with no seam for tests/evals to assert "was an email
        actually sent" against a controllable double. Adds an injectable
        `transport` parameter, defaulting to the real client.
        """
        from app.tools.resend_client import SendResult

        calls = []

        async def fake_transport(*, to_email, from_email, subject, html_body, reply_to=None):
            calls.append({"to_email": to_email, "subject": subject})
            return SendResult(ok=True, provider_message_id="fake_injected_id")

        run_id = await make_run()
        ctx = _context(run_id, org_and_vendor["org_id"])
        result = await send_email(
            ctx,
            SendEmailInput(
                to_email="vendor@example.com", from_email="rowan@example.com",
                template_id="first_outreach", template_vars={"vendor_name": "Test Vendor"},
                vendor_id=org_and_vendor["vendor_id"], sequence=0,
            ),
            transport=fake_transport,
        )
        assert result.status == ToolStatus.ok
        assert result.data.provider_message_id == "fake_injected_id"
        assert len(calls) == 1
        assert calls[0]["to_email"] == "vendor@example.com"
