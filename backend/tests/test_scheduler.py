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


class TestCrashRecoverySweeps:
    """Regression tests for the coordinator/qa-evals-engineer finding #1
    (2026-07-18, severe): the scheduler must be able to resume a run that
    got stuck in `parsing`/`validating`/`filed` (e.g. the webhook process
    that started the cascade crashed partway through) — not just
    `document_received`, which was the only crash-recovery sweep that
    existed before this fix.
    """

    async def test_sweep_advances_run_stuck_in_validating(self, org_and_vendor, make_run):
        from app.ids import uuid7
        from app.models.coi_fields import ExtractedCoiFields, ExtractedCoverageLine
        from app.models.enums import CoverageType
        from app.retrieval import entity_repo

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

        stats = await scheduler_tick(now=date.today())
        assert stats["runs_advanced"] >= 1

        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            run = await run_repo.get_run(conn, run_id)
        assert run.state == RunState.monitoring  # validating -> filed -> monitoring, resumed by the sweep

    async def test_sweep_advances_run_stuck_in_filed(self, org_and_vendor, make_run):
        from app.ids import uuid7
        from app.models.coi_fields import ExtractedCoiFields, ExtractedCoverageLine
        from app.models.enums import CoverageType
        from app.retrieval import entity_repo

        run_id = await make_run(state="filed", due_date=date.today())
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
            ext = await entity_repo.insert_coi_extraction(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                coi_document_id=doc.id, extracted=extraction.model_dump(mode="json"), field_confidence={},
                overall_confidence=0.95, model="t", prompt_hash="p", input_tokens=1, output_tokens=1, cost_cents=1,
            )
            await entity_repo.insert_coi_validation(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                coi_extraction_id=ext.id, result="pass", line_results=[], flags=[], faithfulness_ok=True,
            )
            await conn.execute("update runs set coi_document_id = $2 where id = $1", run_id, doc.id)

        stats = await scheduler_tick(now=date.today())
        assert stats["runs_advanced"] >= 1

        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            run = await run_repo.get_run(conn, run_id)
        assert run.state == RunState.monitoring

    async def test_sweep_advances_run_stuck_in_parsing_with_injected_engine(self, org_and_vendor, make_run, tmp_path):
        from app.ids import uuid7
        from app.models.coi_fields import ExtractedCoiFields, ExtractedCoverageLine
        from app.models.enums import CoverageType
        from app.retrieval import entity_repo
        from app.storage import LocalFilesystemStorage
        from app.tools.parse_document import ExtractionEngineResult

        class FakeEngine:
            async def extract(self, *, document_bytes, content_type, prompt_id, attempt_no):
                return ExtractionEngineResult(
                    extracted=ExtractedCoiFields(
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
                    ),
                    field_confidence={},
                    model="fake-model",
                    prompt_hash="fakehash",
                    input_tokens=10,
                    output_tokens=10,
                    cost_cents=1,
                )

        storage = LocalFilesystemStorage(base_dir=str(tmp_path))
        run_id = await make_run(state="document_received", due_date=date.today())
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            doc = await entity_repo.insert_coi_document(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], vendor_id=org_and_vendor["vendor_id"],
                run_id=run_id, storage_path="x/y.pdf", original_filename="y.pdf", content_type="application/pdf",
                byte_size=10, sha256="abc", source="email_inbound",
                version_number=await entity_repo.next_document_version(conn, org_and_vendor["vendor_id"]),
            )
            await run_repo.update_run_state(
                conn, run_id, from_state=RunState.document_received, to_state=RunState.parsing,
                extra={"coi_document_id": doc.id},
            )
        await storage.write(storage_path=doc.storage_path, data=b"%PDF-1.4\n" + b"0" * 100)

        stats = await scheduler_tick(now=date.today(), engine=FakeEngine(), storage=storage)
        assert stats["runs_advanced"] >= 1

        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            run = await run_repo.get_run(conn, run_id)
        assert run.state == RunState.monitoring  # parsing -> validating -> filed -> monitoring, all resumed

    async def test_sweep_leaves_parsing_run_untouched_when_engine_unconfigured(self, org_and_vendor, make_run):
        """No engine injected (the production default path when
        ANTHROPIC_API_KEY is unset) must not crash the whole sweep — the
        run simply stays in `parsing` for a later, better-configured tick."""
        from app.ids import uuid7
        from app.retrieval import entity_repo

        run_id = await make_run(state="document_received", due_date=date.today())
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            doc = await entity_repo.insert_coi_document(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], vendor_id=org_and_vendor["vendor_id"],
                run_id=run_id, storage_path="x/y.pdf", original_filename="y.pdf", content_type="application/pdf",
                byte_size=10, sha256="abc", source="email_inbound",
                version_number=await entity_repo.next_document_version(conn, org_and_vendor["vendor_id"]),
            )
            await run_repo.update_run_state(
                conn, run_id, from_state=RunState.document_received, to_state=RunState.parsing,
                extra={"coi_document_id": doc.id},
            )

        await scheduler_tick(now=date.today())  # no engine injected

        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            run = await run_repo.get_run(conn, run_id)
        assert run.state == RunState.parsing  # stayed put; no crash
