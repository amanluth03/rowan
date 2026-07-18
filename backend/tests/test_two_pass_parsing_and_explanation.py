"""TDD/characterization tests for agent-engineer's additions:

  1. `run_parsing` now issues TWO sub-calls to `parse_document`
     (prompt_id="classify" then "extract"), per ADR 0004's 2026-07-18
     amendment — see app/orchestration/runner.py::run_parsing.
  2. `needs_human_review` transitions now create an `escalations` row (kind=
     'needs_human_review'), matching ADR 0002's allowlist ("create/update
     escalation(kind=needs_human_review)") and qa-evals-engineer's golden-
     document fixtures (every needs_human_review trajectory expects
     `escalate_to_pm` in `expected_tool_calls`).
  3. Coverage-gap explanation drafting (`_summarize_validation_failure`)
     falls back to a deterministic summary when no Claude engine is
     configured (as in this offline test environment) without ever blocking
     the routing decision.

Uses the SAME live-Postgres fixtures backend-engineer's own tests use
(`org_and_vendor`, `make_run`) — no mocking of the DB layer, only of the LLM
engine (exactly per app/tools/parse_document.py's documented DI seam).
"""

from __future__ import annotations

from datetime import date

import pytest

from app.db import org_scoped_tx
from app.ids import uuid7
from app.models.coi_fields import ExtractedCoiFields, ExtractedCoverageLine
from app.models.enums import CoverageType, RunState
from app.orchestration.runner import run_parsing, run_validation
from app.retrieval import entity_repo
from app.storage import LocalFilesystemStorage
from app.tools.parse_document import ExtractionEngineResult

from tests.test_orchestration_document_pipeline import _clean_extraction, _make_run_in_parsing

pytestmark = pytest.mark.asyncio


class FakeTwoPassEngine:
    """Test double distinguishing classify vs extract sub-calls by
    `prompt_id`, mirroring the real ClaudeExtractionEngine's branching
    (app/tools/extraction_engine.py) without touching the network."""

    def __init__(
        self,
        *,
        is_coi: bool = True,
        document_type: str = "certificate_of_insurance",
        classify_confidence: float = 0.95,
        extraction: ExtractedCoiFields | None = None,
        cost_cents: int = 1,
    ) -> None:
        self.is_coi = is_coi
        self.document_type = document_type
        self.classify_confidence = classify_confidence
        self.extraction = extraction or _clean_extraction()
        self.cost_cents = cost_cents
        self.calls: list[str] = []

    async def extract(self, *, document_bytes, content_type, prompt_id, attempt_no):
        self.calls.append(prompt_id)
        if prompt_id == "classify":
            return ExtractionEngineResult(
                extracted=ExtractedCoiFields(overall_confidence=self.classify_confidence),
                field_confidence={},
                model="fake-classify-model",
                prompt_hash="fake-classify-hash",
                input_tokens=5,
                output_tokens=5,
                cost_cents=self.cost_cents,
                is_coi=self.is_coi,
                document_type=self.document_type,
            )
        if prompt_id == "extract":
            return ExtractionEngineResult(
                extracted=self.extraction,
                field_confidence={},
                model="fake-extract-model",
                prompt_hash="fake-extract-hash",
                input_tokens=10,
                output_tokens=10,
                cost_cents=self.cost_cents,
            )
        raise AssertionError(f"unexpected prompt_id: {prompt_id!r}")


async def _open_escalation(org_id, run_id, reason_code: str):
    async with org_scoped_tx(org_id) as conn:
        row = await conn.fetchrow(
            "select * from escalations where run_id = $1 and reason_code = $2 order by created_at desc limit 1",
            run_id, reason_code,
        )
    return row


class TestClassifySubPass:
    async def test_classify_false_routes_to_needs_human_review_with_escalation(
        self, org_and_vendor, make_run, tmp_path
    ):
        storage = LocalFilesystemStorage(base_dir=str(tmp_path))
        run_id, doc = await _make_run_in_parsing(org_and_vendor, make_run, storage=storage)

        engine = FakeTwoPassEngine(is_coi=False, document_type="invoice")
        result = await run_parsing(org_and_vendor["org_id"], run_id, engine=engine, storage=storage)

        assert result is not None
        assert result.state == RunState.needs_human_review
        # The accuracy-critical extract sub-call must NEVER run once classify
        # says this isn't a COI (ADR 0004: "short-circuits before the
        # extract pass runs").
        assert engine.calls == ["classify"]

        esc = await _open_escalation(org_and_vendor["org_id"], run_id, "unclassifiable_document")
        assert esc is not None
        assert esc["kind"] == "needs_human_review"
        assert "invoice" in esc["summary"]

    async def test_classify_low_confidence_routes_to_needs_human_review(
        self, org_and_vendor, make_run, tmp_path
    ):
        storage = LocalFilesystemStorage(base_dir=str(tmp_path))
        run_id, doc = await _make_run_in_parsing(org_and_vendor, make_run, storage=storage)

        engine = FakeTwoPassEngine(is_coi=True, classify_confidence=0.2)
        result = await run_parsing(org_and_vendor["org_id"], run_id, engine=engine, storage=storage)

        assert result is not None
        assert result.state == RunState.needs_human_review
        assert engine.calls == ["classify"]
        esc = await _open_escalation(org_and_vendor["org_id"], run_id, "unclassifiable_document")
        assert esc is not None

    async def test_classify_true_and_confident_extract_reaches_validating(
        self, org_and_vendor, make_run, tmp_path
    ):
        storage = LocalFilesystemStorage(base_dir=str(tmp_path))
        run_id, doc = await _make_run_in_parsing(org_and_vendor, make_run, storage=storage)

        engine = FakeTwoPassEngine(is_coi=True, extraction=_clean_extraction())
        result = await run_parsing(org_and_vendor["org_id"], run_id, engine=engine, storage=storage)

        assert result is not None
        assert result.state == RunState.validating
        assert engine.calls == ["classify", "extract"]
        # Both sub-passes consumed the shared per-document LLM budget
        # separately (ADR 0004: "both increment llm_calls_this_doc").
        assert result.llm_call_count == 2

    async def test_low_confidence_extract_after_confident_classify_routes_to_needs_human_review(
        self, org_and_vendor, make_run, tmp_path
    ):
        storage = LocalFilesystemStorage(base_dir=str(tmp_path))
        run_id, doc = await _make_run_in_parsing(org_and_vendor, make_run, storage=storage)

        engine = FakeTwoPassEngine(is_coi=True, extraction=_clean_extraction(overall_confidence=0.3))
        result = await run_parsing(org_and_vendor["org_id"], run_id, engine=engine, storage=storage)

        assert result is not None
        assert result.state == RunState.needs_human_review
        assert engine.calls == ["classify", "extract"]
        esc = await _open_escalation(org_and_vendor["org_id"], run_id, "low_confidence_extraction")
        assert esc is not None

    async def test_llm_budget_exhausted_before_classify_skips_engine_entirely(
        self, org_and_vendor, make_run, tmp_path
    ):
        storage = LocalFilesystemStorage(base_dir=str(tmp_path))
        run_id, doc = await _make_run_in_parsing(org_and_vendor, make_run, storage=storage)
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            await conn.execute("update runs set llm_call_count = 5 where id = $1", run_id)

        engine = FakeTwoPassEngine()
        result = await run_parsing(org_and_vendor["org_id"], run_id, engine=engine, storage=storage)

        assert result is not None
        assert result.state == RunState.needs_human_review
        assert engine.calls == []  # never called: budget denied before any sub-call
        esc = await _open_escalation(org_and_vendor["org_id"], run_id, "extraction_budget_exhausted")
        assert esc is not None

    async def test_llm_budget_exhausted_between_classify_and_extract(
        self, org_and_vendor, make_run, tmp_path
    ):
        storage = LocalFilesystemStorage(base_dir=str(tmp_path))
        run_id, doc = await _make_run_in_parsing(org_and_vendor, make_run, storage=storage)
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            await conn.execute("update runs set llm_call_count = 4 where id = $1", run_id)

        engine = FakeTwoPassEngine(is_coi=True)
        result = await run_parsing(org_and_vendor["org_id"], run_id, engine=engine, storage=storage)

        assert result is not None
        assert result.state == RunState.needs_human_review
        # classify ran (consuming slot 5/5); extract never got the chance.
        assert engine.calls == ["classify"]
        esc = await _open_escalation(org_and_vendor["org_id"], run_id, "extraction_budget_exhausted")
        assert esc is not None


class TestValidationFailureEscalation:
    async def _make_run_in_validating(self, org_and_vendor, make_run, extraction: ExtractedCoiFields):
        run_id = await make_run(state="validating", due_date=date.today())
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            doc = await entity_repo.insert_coi_document(
                conn,
                id=uuid7(),
                organization_id=org_and_vendor["org_id"],
                vendor_id=org_and_vendor["vendor_id"],
                run_id=run_id,
                storage_path="x/y.pdf",
                original_filename="y.pdf",
                content_type="application/pdf",
                byte_size=10,
                sha256="abc",
                source="email_inbound",
                version_number=await entity_repo.next_document_version(conn, org_and_vendor["vendor_id"]),
            )
            ext = await entity_repo.insert_coi_extraction(
                conn,
                id=uuid7(),
                organization_id=org_and_vendor["org_id"],
                run_id=run_id,
                coi_document_id=doc.id,
                extracted=extraction.model_dump(mode="json"),
                field_confidence={},
                overall_confidence=extraction.overall_confidence,
                model="t",
                prompt_hash="p",
                input_tokens=1,
                output_tokens=1,
                cost_cents=1,
            )
            await conn.execute("update runs set coi_document_id = $2 where id = $1", run_id, doc.id)
        return run_id, doc, ext

    async def test_validation_failure_creates_needs_human_review_escalation_with_fallback_summary(
        self, org_and_vendor, make_run
    ):
        bad = _clean_extraction(
            coverage_lines=[
                ExtractedCoverageLine(
                    coverage_type=CoverageType.general_liability,
                    each_occurrence=100,
                    aggregate=100,
                    additional_insured=True,
                    confidence=0.95,
                )
            ]
        )
        run_id, doc, ext = await self._make_run_in_validating(org_and_vendor, make_run, bad)
        result = await run_validation(org_and_vendor["org_id"], run_id)

        assert result is not None
        assert result.state == RunState.needs_human_review

        esc = await _open_escalation(org_and_vendor["org_id"], run_id, "validation_failed")
        assert esc is not None
        assert esc["kind"] == "needs_human_review"
        # No ANTHROPIC_API_KEY is configured in this test environment, so
        # _default_explanation_engine() returns None and the deterministic
        # fallback summary (never LLM prose) must be used — and the
        # escalation must still exist and be well-formed either way (ADR
        # 0004: drafting failure never blocks the escalation).
        assert org_and_vendor["vendor_id"] is not None  # sanity: fixture wired
        assert "did not pass automated coverage validation" in esc["summary"]
