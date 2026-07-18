"""TDD: document_received -> parsing -> validating -> filed |
needs_human_review | escalated_to_pm -> monitoring (ADR 0002). Covers the
qa-evals-engineer design question: both `no_requirements_on_file` (empty
requirement set) and a partially-unbacked requirement line
(`faithfulness_ok=False`) must route validating -> escalated_to_pm, per
ADR 0005, not fall through to needs_human_review.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.db import org_scoped_tx
from app.ids import uuid7
from app.models.coi_fields import ExtractedCoiFields, ExtractedCoverageLine
from app.models.enums import CoverageType, RunState
from app.orchestration.runner import (
    advance_from_document_received,
    handle_inbound_document,
    run_parsing,
    run_validation,
)
from app.retrieval import entity_repo, run_repo
from app.tools.parse_document import ExtractionEngineResult

pytestmark = pytest.mark.asyncio


class FakeEngine:
    """Test double for agent-engineer's ExtractionEngine — returns a
    caller-supplied ExtractedCoiFields instead of calling Claude."""

    def __init__(self, extracted: ExtractedCoiFields, *, model="fake-model", cost_cents=1):
        self.extracted = extracted
        self.model = model
        self.cost_cents = cost_cents

    async def extract(self, *, document_bytes, content_type, prompt_id, attempt_no):
        return ExtractionEngineResult(
            extracted=self.extracted,
            field_confidence={},
            model=self.model,
            prompt_hash="fakehash",
            input_tokens=10,
            output_tokens=10,
            cost_cents=self.cost_cents,
        )


PDF_MAGIC = b"%PDF-1.4\n%fake pdf content for tests\n" + b"0" * 100


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


async def test_handle_inbound_document_stores_and_transitions_to_parsing(org_and_vendor, make_run):
    run_id = await make_run(state="awaiting_vendor_response", due_date=date.today())
    result = await handle_inbound_document(
        org_and_vendor["org_id"], run_id, filename="coi.pdf", data=PDF_MAGIC, content_type="application/pdf"
    )
    assert result is not None
    assert result.state == RunState.parsing
    assert result.coi_document_id is not None


async def test_handle_inbound_document_rejects_disallowed_file_type(org_and_vendor, make_run):
    run_id = await make_run(state="awaiting_vendor_response", due_date=date.today())
    result = await handle_inbound_document(
        org_and_vendor["org_id"], run_id, filename="virus.exe", data=b"MZ" + b"0" * 50, content_type="application/octet-stream"
    )
    # Guardrail rejects the file; run stays in awaiting_vendor_response, no
    # transition, no document row created.
    assert result is None
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        run = await run_repo.get_run(conn, run_id)
    assert run.state == RunState.awaiting_vendor_response


async def test_handle_inbound_document_never_uses_raw_filename_in_storage_path(
    org_and_vendor, make_run, tmp_path, admin_conn
):
    """security-reviewer's blocking finding (2026-07-18): storage_path was
    built as f"{vendor_id}/{document_id}_{filename}" using the raw,
    UNTRUSTED inbound attachment filename directly — a filename like
    "../../../../tmp/evil.pdf" passed the (then-extension-only) guardrail
    and escaped LocalFilesystemStorage's base_dir on write. Fixed two ways:
    (1) file_guardrails.check_attachment now rejects unsafe filenames
    outright (tests/test_file_guardrails.py), and (2) independently, as
    defense-in-depth, the storage path is no longer derived from the
    filename AT ALL — this test proves that even for a filename that WOULD
    pass every other guardrail, it never appears in the stored path.
    """
    from app.storage import LocalFilesystemStorage

    storage = LocalFilesystemStorage(base_dir=str(tmp_path))
    run_id = await make_run(state="awaiting_vendor_response", due_date=date.today())

    # A filename that is benign-looking but distinctive, to prove it's
    # absent from the resulting storage path/on-disk location.
    distinctive_filename = "SENTINEL_MARKER_do_not_appear_in_path.pdf"
    result = await handle_inbound_document(
        org_and_vendor["org_id"], run_id, filename=distinctive_filename, data=PDF_MAGIC,
        content_type="application/pdf", storage=storage,
    )
    assert result is not None

    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        doc = await entity_repo.get_coi_document(conn, result.coi_document_id)
    assert "SENTINEL_MARKER" not in doc.storage_path
    assert doc.original_filename == distinctive_filename  # still recorded as metadata

    # And a genuinely hostile filename is caught by the hardened guardrail
    # before ever reaching storage.write() at all. (First deactivate the
    # earlier run — only one ACTIVE run per vendor is allowed.)
    await admin_conn.execute("update runs set status = 'completed' where id = $1", run_id)
    run_id2 = await make_run(state="awaiting_vendor_response", due_date=date.today())
    malicious_result = await handle_inbound_document(
        org_and_vendor["org_id"], run_id2, filename="../../../../tmp/evil.pdf", data=PDF_MAGIC,
        content_type="application/pdf", storage=storage,
    )
    assert malicious_result is None
    escaped_path = tmp_path.parent / "tmp" / "evil.pdf"
    assert not escaped_path.exists()


async def _make_run_in_parsing(org_and_vendor, make_run, *, storage, data=PDF_MAGIC):
    run_id = await make_run(state="document_received", due_date=date.today())
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        doc = await entity_repo.insert_coi_document(
            conn, id=uuid7(), organization_id=org_and_vendor["org_id"], vendor_id=org_and_vendor["vendor_id"],
            run_id=run_id, storage_path="x/y.pdf", original_filename="y.pdf", content_type="application/pdf",
            byte_size=len(data), sha256="abc", source="email_inbound",
            version_number=await entity_repo.next_document_version(conn, org_and_vendor["vendor_id"]),
        )
        await run_repo.update_run_state(
            conn, run_id, from_state=RunState.document_received, to_state=RunState.parsing,
            extra={"coi_document_id": doc.id},
        )
    await storage.write(storage_path=doc.storage_path, data=data)
    return run_id, doc


async def test_parsing_transitions_to_validating_on_confident_extraction(org_and_vendor, make_run, tmp_path):
    from app.storage import LocalFilesystemStorage

    storage = LocalFilesystemStorage(base_dir=str(tmp_path))
    run_id, doc = await _make_run_in_parsing(org_and_vendor, make_run, storage=storage)

    engine = FakeEngine(_clean_extraction())
    result = await run_parsing(org_and_vendor["org_id"], run_id, engine=engine, storage=storage)
    assert result is not None
    assert result.state == RunState.validating


async def test_parsing_routes_to_needs_human_review_on_low_confidence(org_and_vendor, make_run, tmp_path):
    from app.storage import LocalFilesystemStorage

    storage = LocalFilesystemStorage(base_dir=str(tmp_path))
    run_id, doc = await _make_run_in_parsing(org_and_vendor, make_run, storage=storage)

    engine = FakeEngine(_clean_extraction(overall_confidence=0.3))
    result = await run_parsing(org_and_vendor["org_id"], run_id, engine=engine, storage=storage)
    assert result is not None
    assert result.state == RunState.needs_human_review


async def _make_run_in_validating(org_and_vendor, make_run, extraction: ExtractedCoiFields):
    run_id = await make_run(state="validating", due_date=date.today())
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
            overall_confidence=extraction.overall_confidence, model="t", prompt_hash="p",
            input_tokens=1, output_tokens=1, cost_cents=1,
        )
        # make_run already created the row directly in 'validating' state;
        # just set coi_document_id (a plain UPDATE, not a CAS transition —
        # this is test setup, not something under test here).
        await conn.execute("update runs set coi_document_id = $2 where id = $1", run_id, doc.id)
    return run_id, doc, ext


async def test_validation_pass_routes_to_filed(org_and_vendor, make_run):
    run_id, doc, ext = await _make_run_in_validating(org_and_vendor, make_run, _clean_extraction())
    result = await run_validation(org_and_vendor["org_id"], run_id)
    assert result is not None
    assert result.state == RunState.filed


async def test_validation_fail_routes_to_needs_human_review(org_and_vendor, make_run):
    bad = _clean_extraction(
        coverage_lines=[
            ExtractedCoverageLine(
                coverage_type=CoverageType.general_liability,
                each_occurrence=100,  # far below minimum
                aggregate=100,
                additional_insured=True,
                confidence=0.95,
            )
        ]
    )
    run_id, doc, ext = await _make_run_in_validating(org_and_vendor, make_run, bad)
    result = await run_validation(org_and_vendor["org_id"], run_id)
    assert result is not None
    assert result.state == RunState.needs_human_review


async def test_no_requirements_on_file_routes_to_escalated_to_pm(org_and_vendor, make_run, admin_conn):
    # Remove the vendor's requirement set entirely.
    await admin_conn.execute(
        "delete from vendor_coverage_requirements where vendor_id = $1", org_and_vendor["vendor_id"]
    )
    run_id, doc, ext = await _make_run_in_validating(org_and_vendor, make_run, _clean_extraction())
    result = await run_validation(org_and_vendor["org_id"], run_id)
    assert result is not None
    assert result.state == RunState.escalated_to_pm


async def test_cost_cents_spent_accumulates_across_documents_in_same_run_cycle(org_and_vendor, make_run):
    """Regression test for a bug the architect caught: BUDGET_COST_CAP_CENTS
    is a per-RUN-CYCLE cap (CLAUDE.md: "max configurable $ per run"), not
    per-document. `advance_from_document_received` must reset
    `llm_call_count` (per-document, by design) when a new document enters
    parsing, but must NOT reset `cost_cents_spent` — otherwise repeated
    PM-requested revisions across multiple documents in the same run could
    blow past the configured per-run cap in unbounded per-document
    increments.
    """
    run_id = await make_run(state="document_received", due_date=date.today(), cost_cents_spent=50, llm_call_count=3)

    # First document enters parsing: llm_call_count resets (fresh per-doc
    # budget), but the run has already spent 50c and that must carry over.
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        doc1 = await entity_repo.insert_coi_document(
            conn, id=uuid7(), organization_id=org_and_vendor["org_id"], vendor_id=org_and_vendor["vendor_id"],
            run_id=run_id, storage_path="x/doc1.pdf", original_filename="doc1.pdf", content_type="application/pdf",
            byte_size=10, sha256="doc1", source="email_inbound",
            version_number=await entity_repo.next_document_version(conn, org_and_vendor["vendor_id"]),
        )
        await conn.execute("update runs set coi_document_id = $2 where id = $1", run_id, doc1.id)

    result1 = await advance_from_document_received(org_and_vendor["org_id"], run_id)
    assert result1 is not None
    assert result1.state == RunState.parsing
    assert result1.llm_call_count == 0, "llm_call_count must reset per new document"
    assert result1.cost_cents_spent == 50, "cost_cents_spent must NOT reset — it's a per-run-cycle cap"

    # Simulate spend during doc1's parse attempts, then a PM-requested
    # revision brings in doc2 (document_received -> parsing again).
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        await run_repo.update_run_state(
            conn, run_id, from_state=RunState.parsing, to_state=RunState.needs_human_review,
        )
        await run_repo.increment_counters(conn, run_id, cost_cents_delta=30)  # doc1's parse cost
        await run_repo.update_run_state(
            conn, run_id, from_state=RunState.needs_human_review, to_state=RunState.awaiting_vendor_response,
        )
        await run_repo.update_run_state(
            conn, run_id, from_state=RunState.awaiting_vendor_response, to_state=RunState.document_received,
        )
        doc2 = await entity_repo.insert_coi_document(
            conn, id=uuid7(), organization_id=org_and_vendor["org_id"], vendor_id=org_and_vendor["vendor_id"],
            run_id=run_id, storage_path="x/doc2.pdf", original_filename="doc2.pdf", content_type="application/pdf",
            byte_size=10, sha256="doc2", source="email_inbound",
            version_number=await entity_repo.next_document_version(conn, org_and_vendor["vendor_id"]),
        )
        await conn.execute("update runs set coi_document_id = $2 where id = $1", run_id, doc2.id)

    result2 = await advance_from_document_received(org_and_vendor["org_id"], run_id)
    assert result2 is not None
    assert result2.state == RunState.parsing
    assert result2.llm_call_count == 0, "llm_call_count resets again for the NEW document"
    assert result2.cost_cents_spent == 80, "cost_cents_spent must keep accumulating across documents (50 + 30)"


async def test_unbacked_requirement_line_routes_to_escalated_to_pm_not_needs_human_review(
    org_and_vendor, make_run, admin_conn
):
    """qa-evals-engineer's design question: a partially-unbacked requirement
    (faithfulness_ok=False via unverified_requirement) must be treated the
    SAME as no_requirements_on_file — escalated_to_pm, not needs_human_review
    — per ADR 0005's structural faithfulness routing."""
    await admin_conn.execute(
        "update vendor_coverage_requirements set source_compliance_requirement_id = null where vendor_id = $1",
        org_and_vendor["vendor_id"],
    )
    run_id, doc, ext = await _make_run_in_validating(org_and_vendor, make_run, _clean_extraction())
    result = await run_validation(org_and_vendor["org_id"], run_id)
    assert result is not None
    assert result.state == RunState.escalated_to_pm
