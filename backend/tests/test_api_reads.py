"""HTTP-layer tests for app/api/reads.py — the four ADR 0003 read-model
DTOs (RunTraceDTO, ActivityFeedItemDTO, VendorStatusDTO, ReviewQueueItemDTO)
plus the document-download route. Includes the specific regression test
requested by the integration-pass brief: the review queue must find an open
escalation by kind+status, NOT by matching the run's CURRENT state against
`escalations.details.run_state` (the shape `escalate_to_pm`'s OWN internal
dedupe uses, which is NOT what a read/dispatch path should reuse).
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.db import org_scoped_tx
from app.ids import uuid7
from app.models.coi_fields import ExtractedCoiFields, ExtractedCoverageLine
from app.models.enums import CoverageType
from app.orchestration.runner import add_vendor
from app.retrieval import entity_repo
from app.tools.validation_logic import evaluate_validation

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def client():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def _headers(org_id) -> dict:
    return {"X-Rowan-Org-Id": str(org_id)}


class TestVendorStatus:
    async def test_list_and_get_vendor(self, client, org_and_vendor):
        resp = await client.get("/api/v1/vendors", headers=_headers(org_and_vendor["org_id"]))
        assert resp.status_code == 200
        vendors = resp.json()
        assert any(v["id"] == str(org_and_vendor["vendor_id"]) for v in vendors)

        resp = await client.get(
            f"/api/v1/vendors/{org_and_vendor['vendor_id']}", headers=_headers(org_and_vendor["org_id"])
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Test Vendor"
        assert body["primaryPropertyJurisdiction"] == "Boston, MA"
        assert len(body["requirements"]) == 1
        assert body["complianceStatus"] in {
            "compliant", "expiring_soon", "needs_review", "escalated", "no_requirements", "pending",
        }

    async def test_get_unknown_vendor_404(self, client, org_and_vendor):
        resp = await client.get(f"/api/v1/vendors/{uuid7()}", headers=_headers(org_and_vendor["org_id"]))
        assert resp.status_code == 404

    async def test_vendor_from_other_org_is_404(self, client, org_and_vendor):
        other_org = uuid7()
        resp = await client.get(f"/api/v1/vendors/{org_and_vendor['vendor_id']}", headers=_headers(other_org))
        assert resp.status_code == 404

    async def test_no_requirements_status_before_set_requirements(self, client, org_and_vendor):
        vendor, run = await add_vendor(
            org_and_vendor["org_id"], name="Bare Vendor", primary_email="bare@x.example.com",
            vendor_role="cleaner", primary_property_id=None, notes=None, due_date=None,
        )
        resp = await client.get(f"/api/v1/vendors/{vendor.id}", headers=_headers(org_and_vendor["org_id"]))
        assert resp.status_code == 200
        assert resp.json()["complianceStatus"] == "no_requirements"


class TestRunTrace:
    async def test_trace_includes_transition_events(self, client, org_and_vendor, make_run):
        from app.orchestration.runner import send_first_outreach

        run_id = await make_run(state="renewal_due_soon", due_date=date.today())
        await send_first_outreach(org_and_vendor["org_id"], run_id)

        resp = await client.get(f"/api/v1/runs/{run_id}/trace", headers=_headers(org_and_vendor["org_id"]))
        assert resp.status_code == 200
        body = resp.json()
        assert body["runId"] == str(run_id)
        assert body["state"] == "awaiting_vendor_response"
        assert body["budget"]["outreachEmailCount"] == 1
        event_names = [e["name"] for e in body["events"]]
        assert "run.renewal_due_soon_to_first_outreach_sent" in event_names
        assert "run.first_outreach_sent_to_awaiting_vendor_response" in event_names

    async def test_unknown_run_404(self, client, org_and_vendor):
        resp = await client.get(f"/api/v1/runs/{uuid7()}/trace", headers=_headers(org_and_vendor["org_id"]))
        assert resp.status_code == 404


class TestActivityFeed:
    async def test_feed_surfaces_outreach_sent(self, client, org_and_vendor, make_run):
        from app.orchestration.runner import send_first_outreach

        run_id = await make_run(state="renewal_due_soon", due_date=date.today())
        await send_first_outreach(org_and_vendor["org_id"], run_id)

        resp = await client.get("/api/v1/activity-feed", headers=_headers(org_and_vendor["org_id"]))
        assert resp.status_code == 200
        items = resp.json()
        matching = [i for i in items if i["runId"] == str(run_id)]
        assert any(i["kind"] == "outreach_sent" for i in matching)
        assert all(i["vendorName"] == "Test Vendor" for i in matching)


class TestReviewQueue:
    async def _make_failing_validation(self, org_and_vendor, make_run):
        run_id = await make_run(state="needs_human_review", due_date=date.today())
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            doc = await entity_repo.insert_coi_document(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"],
                vendor_id=org_and_vendor["vendor_id"], run_id=run_id, storage_path="x/y.pdf",
                original_filename="y.pdf", content_type="application/pdf", byte_size=10, sha256="abc",
                source="email_inbound",
                version_number=await entity_repo.next_document_version(conn, org_and_vendor["vendor_id"]),
            )
            requirements = await entity_repo.get_vendor_coverage_requirements(conn, org_and_vendor["vendor_id"])
            extraction_fields = ExtractedCoiFields(
                policy_effective_date=date(2026, 1, 1),
                policy_expiration_date=date(2027, 1, 1),
                coverage_lines=[
                    ExtractedCoverageLine(
                        coverage_type=CoverageType.general_liability,
                        each_occurrence=500_000,  # below the seeded $1M minimum -> fails
                        aggregate=1_000_000,
                        additional_insured=True,
                        confidence=0.95,
                    )
                ],
                overall_confidence=0.95,
            )
            outcome = evaluate_validation(
                requirements=requirements,
                extraction=extraction_fields,
                active_kb_ids={org_and_vendor["requirement_id"]},
                confidence_threshold=0.80,
            )
            ext = await entity_repo.insert_coi_extraction(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                coi_document_id=doc.id, extracted=extraction_fields.model_dump(mode="json"),
                field_confidence={}, overall_confidence=0.95, model="t", prompt_hash="p",
                input_tokens=1, output_tokens=1, cost_cents=1,
            )
            validation = await entity_repo.insert_coi_validation(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                coi_extraction_id=ext.id, result=outcome.result, line_results=outcome.line_results,
                flags=outcome.flags, faithfulness_ok=outcome.faithfulness_ok,
            )
            await conn.execute("update runs set coi_document_id = $2 where id = $1", run_id, doc.id)
            esc = await entity_repo.insert_escalation(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                vendor_id=org_and_vendor["vendor_id"], kind="needs_human_review", reason_code="validation_failed",
                severity="warn", summary="Coverage below minimum.",
                details={"run_state": "needs_human_review", "validation_id": str(validation.id)},
            )
        return run_id, doc, validation, esc

    async def test_review_queue_item_has_comparison_and_faithfulness(self, client, org_and_vendor, make_run):
        run_id, doc, validation, esc = await self._make_failing_validation(org_and_vendor, make_run)

        resp = await client.get("/api/v1/reviews", headers=_headers(org_and_vendor["org_id"]))
        assert resp.status_code == 200
        items = resp.json()
        item = next(i for i in items if i["escalationId"] == str(esc.id))
        assert item["faithfulnessOk"] is True
        assert item["overallConfidence"] == pytest.approx(0.95)
        assert len(item["comparison"]) == 1
        line = item["comparison"][0]
        assert line["pass"] is False
        assert line["required"]["minEachOccurrence"] == 1_000_000
        assert line["parsed"]["eachOccurrence"] == 500_000
        assert line["required"]["sourceCitation"] == "test citation"
        assert item["document"]["url"] == f"/api/v1/documents/{doc.id}/download"

        resp = await client.get(f"/api/v1/reviews/{esc.id}", headers=_headers(org_and_vendor["org_id"]))
        assert resp.status_code == 200
        assert resp.json()["escalationId"] == str(esc.id)

    async def test_review_queue_finds_escalation_even_if_run_state_has_moved_on(
        self, client, org_and_vendor, make_run
    ):
        """The exact gap security-reviewer flagged: `escalate_to_pm`'s
        internal dedupe (`entity_repo.get_open_escalation`) keys on
        `details.run_state` matching the run's state AT ESCALATION-CREATION
        TIME -- that is a valid mechanism for ITS purpose (idempotent
        re-entry into the SAME open escalation from the SAME state), but the
        review-QUEUE read path must not reuse that shape: it has to surface
        an open escalation regardless of what the run has done since. Here
        the run is left in a state (`monitoring`) that doesn't match the
        escalation's stamped `details.run_state` at all, and the escalation
        is deliberately NOT the run's only/latest activity -- proving the
        queue endpoint filters purely on kind+status, never on run.state.
        """
        run_id = await make_run(state="monitoring", due_date=date.today())
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            esc = await entity_repo.insert_escalation(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                vendor_id=org_and_vendor["vendor_id"], kind="needs_human_review", reason_code="validation_failed",
                severity="warn", summary="Stale-state escalation.",
                details={"run_state": "needs_human_review"},  # stamped, but run is now 'monitoring'
            )

        resp = await client.get(
            "/api/v1/reviews", params={"kind": "needs_human_review"}, headers=_headers(org_and_vendor["org_id"])
        )
        assert resp.status_code == 200
        ids = [i["escalationId"] for i in resp.json()]
        assert str(esc.id) in ids

        resp = await client.get(f"/api/v1/reviews/{esc.id}", headers=_headers(org_and_vendor["org_id"]))
        assert resp.status_code == 200
        assert resp.json()["status"] == "open"

    async def test_resolved_escalation_not_in_open_queue(self, client, org_and_vendor, make_run):
        run_id = await make_run(state="needs_human_review", due_date=date.today())
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            esc = await entity_repo.insert_escalation(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                vendor_id=org_and_vendor["vendor_id"], kind="needs_human_review", reason_code="validation_failed",
                severity="warn", summary="test", details={"run_state": "needs_human_review"},
            )
            await entity_repo.resolve_escalation(conn, escalation_id=esc.id, resolution="approved", resolved_by=None)

        resp = await client.get("/api/v1/reviews", headers=_headers(org_and_vendor["org_id"]))
        ids = [i["escalationId"] for i in resp.json()]
        assert str(esc.id) not in ids


class TestDocumentDownload:
    async def test_download_returns_bytes_with_sanitized_filename(self, client, org_and_vendor, make_run, tmp_path, monkeypatch):
        from app import storage as storage_module

        monkeypatch.setattr(storage_module, "_default_storage", storage_module.LocalFilesystemStorage(str(tmp_path)))

        run_id = await make_run(state="document_received", due_date=date.today())
        raw_filename = 'evil.pdf\r\nX-Injected: pwned\r\n".pdf'
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            doc = await entity_repo.insert_coi_document(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"],
                vendor_id=org_and_vendor["vendor_id"], run_id=run_id, storage_path=f"{doc_id_path(run_id)}",
                original_filename=raw_filename, content_type="application/pdf\r\nX-Evil: 1", byte_size=4,
                sha256="abc", source="email_inbound",
                version_number=await entity_repo.next_document_version(conn, org_and_vendor["vendor_id"]),
            )
        await storage_module.get_storage().write(storage_path=doc.storage_path, data=b"%PDF")

        resp = await client.get(f"/api/v1/documents/{doc.id}/download", headers=_headers(org_and_vendor["org_id"]))
        assert resp.status_code == 200
        assert resp.content == b"%PDF"
        # The real security property: no CR/LF reached the response (which
        # would let "X-Injected: pwned" become its OWN header line instead
        # of inert text inside filename="..."). With CR/LF stripped, that
        # substring surviving as harmless text inside the quoted filename is
        # expected and fine -- it's no longer an injection, just ugly text.
        cd = resp.headers["content-disposition"]
        assert "\r" not in cd and "\n" not in cd
        assert "x-injected" not in [k.lower() for k in resp.headers.keys()]
        ct = resp.headers["content-type"]
        assert "\r" not in ct and "\n" not in ct
        assert "x-evil" not in [k.lower() for k in resp.headers.keys()]

    async def test_download_unknown_document_404(self, client, org_and_vendor):
        resp = await client.get(f"/api/v1/documents/{uuid7()}/download", headers=_headers(org_and_vendor["org_id"]))
        assert resp.status_code == 404

    async def test_download_ignores_attacker_controlled_content_type(
        self, client, org_and_vendor, make_run, tmp_path, monkeypatch
    ):
        """security-reviewer BLOCK (2026-07-18): coi_documents.content_type
        is the inbound webhook's attacker-supplied MIME string, stored
        verbatim and previously echoed straight into the response
        Content-Type. Combined with the ingest guardrail only checking a
        magic-byte PREFIX (so a PDF-polyglot containing HTML/JS passes),
        Content-Disposition: inline, and no nosniff header, a vendor could
        get a PM's browser to render/execute arbitrary attacker content —
        exactly CLAUDE.md's "malicious COI -> exfiltrate data" highest-risk
        surface. Fixed: media type is now derived ONLY from the
        guardrail-detected type recoverable from storage_path's extension
        (never from the untrusted content_type column), the response always
        carries X-Content-Type-Options: nosniff, and these evidence files
        are served as attachments, never inline.
        """
        from app import storage as storage_module

        monkeypatch.setattr(storage_module, "_default_storage", storage_module.LocalFilesystemStorage(str(tmp_path)))

        run_id = await make_run(state="document_received", due_date=date.today())
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            doc = await entity_repo.insert_coi_document(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"],
                vendor_id=org_and_vendor["vendor_id"], run_id=run_id,
                storage_path=f"attacker-test/{run_id}.pdf",
                original_filename="coi.pdf",
                # Attacker-controlled inbound MIME string — spoofed to an
                # HTML type despite the guardrail-detected/stored type being
                # PDF (storage_path's extension). This must NEVER reach the
                # response as-is.
                content_type="text/html; charset=utf-8",
                byte_size=4, sha256="abc", source="email_inbound",
                version_number=await entity_repo.next_document_version(conn, org_and_vendor["vendor_id"]),
            )
        # Polyglot payload: starts with a valid PDF magic-byte prefix (so
        # any prefix-only sniffing/guardrail would call it a PDF) but also
        # contains an embedded HTML/script payload later in the file.
        polyglot = b"%PDF-1.4\n" + b"<script>alert(document.cookie)</script>\n" + b"0" * 50
        await storage_module.get_storage().write(storage_path=doc.storage_path, data=polyglot)

        resp = await client.get(f"/api/v1/documents/{doc.id}/download", headers=_headers(org_and_vendor["org_id"]))
        assert resp.status_code == 200

        content_type = resp.headers["content-type"]
        assert "html" not in content_type.lower(), (
            f"attacker-controlled content_type leaked into the response: {content_type!r}"
        )
        assert content_type.split(";")[0].strip() == "application/pdf"

        assert resp.headers.get("x-content-type-options", "").lower() == "nosniff"

        content_disposition = resp.headers["content-disposition"]
        assert content_disposition.lower().startswith("attachment"), (
            f"evidence files must not be served inline: {content_disposition!r}"
        )


def doc_id_path(run_id) -> str:
    return f"test-downloads/{run_id}.pdf"
