"""HTTP-layer tests for app/api/commands.py — the 9 ADR 0003 commands as
FastAPI routes. Exercises the org-scoping dev-auth stub (app/api/deps.py)
and the HTTP shape (status codes, camelCase JSON) on top of the
orchestration-layer behavior already covered by
tests/test_orchestration_commands.py.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.db import org_scoped_tx
from app.ids import uuid7
from app.retrieval import entity_repo

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def client():
    # Same rationale as tests/test_main_app.py's `client` fixture: pools are
    # owned by conftest.py's session-scoped `_pools` fixture.
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def _headers(org_id) -> dict:
    return {"X-Rowan-Org-Id": str(org_id)}


class TestOrgHeaderStub:
    async def test_missing_org_header_is_401(self, client):
        resp = await client.get("/api/v1/vendors")
        assert resp.status_code == 401

    async def test_malformed_org_header_is_400(self, client):
        resp = await client.get("/api/v1/vendors", headers={"X-Rowan-Org-Id": "not-a-uuid"})
        assert resp.status_code == 400


class TestAddVendor:
    async def test_add_vendor_201(self, client, org_and_vendor):
        resp = await client.post(
            "/api/v1/vendors",
            json={
                "name": "HTTP Test Vendor",
                "primaryEmail": "http@vendor.example.com",
                "vendorRole": "electrician",
                "primaryPropertyId": str(org_and_vendor["property_id"]),
                "dueDate": "2027-06-01",
            },
            headers=_headers(org_and_vendor["org_id"]),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["vendorId"]
        assert body["runId"]
        assert body["runState"] == "monitoring"
        assert len(body["replyToken"]) >= 32

    async def test_add_vendor_unknown_property_422(self, client, org_and_vendor):
        resp = await client.post(
            "/api/v1/vendors",
            json={"name": "Bad Co", "vendorRole": "plumber", "primaryPropertyId": str(uuid7())},
            headers=_headers(org_and_vendor["org_id"]),
        )
        assert resp.status_code == 422

    async def test_add_vendor_invalid_body_422(self, client, org_and_vendor):
        resp = await client.post(
            "/api/v1/vendors",
            json={"name": "", "vendorRole": "not_a_real_role"},
            headers=_headers(org_and_vendor["org_id"]),
        )
        assert resp.status_code == 422


class TestSetRequirements:
    async def test_auto_retrieve_200(self, client, org_and_vendor):
        resp = await client.post(
            f"/api/v1/vendors/{org_and_vendor['vendor_id']}/requirements",
            json={},
            headers=_headers(org_and_vendor["org_id"]),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["requirements"]) == 1
        line = body["requirements"][0]
        assert line["coverageType"] == "general_liability"
        assert line["sourceCitation"] == "test citation"
        assert line["confirmedByPm"] is True

    async def test_no_kb_match_422(self, client, org_and_vendor, admin_conn):
        await admin_conn.execute(
            "update vendors set primary_property_id = null where id = $1", org_and_vendor["vendor_id"]
        )
        resp = await client.post(
            f"/api/v1/vendors/{org_and_vendor['vendor_id']}/requirements",
            json={},
            headers=_headers(org_and_vendor["org_id"]),
        )
        assert resp.status_code == 422


class TestRunLifecycle:
    async def test_start_pause_resume(self, client, org_and_vendor, make_run):
        run_id = await make_run(state="monitoring", due_date=date.today())

        resp = await client.post(f"/api/v1/runs/{run_id}/start", headers=_headers(org_and_vendor["org_id"]))
        assert resp.status_code == 200, resp.text
        assert resp.json()["state"] == "awaiting_vendor_response"

        resp = await client.post(f"/api/v1/runs/{run_id}/pause", headers=_headers(org_and_vendor["org_id"]))
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"

        resp = await client.post(f"/api/v1/runs/{run_id}/resume", headers=_headers(org_and_vendor["org_id"]))
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

    async def test_start_run_unknown_run_409(self, client, org_and_vendor):
        resp = await client.post(f"/api/v1/runs/{uuid7()}/start", headers=_headers(org_and_vendor["org_id"]))
        assert resp.status_code == 409

    async def test_pause_twice_second_call_409(self, client, org_and_vendor, make_run):
        run_id = await make_run(state="monitoring")
        resp = await client.post(f"/api/v1/runs/{run_id}/pause", headers=_headers(org_and_vendor["org_id"]))
        assert resp.status_code == 200
        resp = await client.post(f"/api/v1/runs/{run_id}/pause", headers=_headers(org_and_vendor["org_id"]))
        assert resp.status_code == 409


class TestReviewQueueCommands:
    async def test_approve_review_via_http(self, client, org_and_vendor, make_run):
        run_id = await make_run(state="needs_human_review", due_date=date.today())
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            esc = await entity_repo.insert_escalation(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                vendor_id=org_and_vendor["vendor_id"], kind="needs_human_review", reason_code="validation_failed",
                severity="warn", summary="test", details={"run_state": "needs_human_review"},
            )
        resp = await client.post(
            f"/api/v1/reviews/{esc.id}/approve", json={}, headers=_headers(org_and_vendor["org_id"])
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["runState"] == "filed"

    async def test_reject_review_via_http(self, client, org_and_vendor, make_run):
        run_id = await make_run(state="needs_human_review", due_date=date.today())
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            esc = await entity_repo.insert_escalation(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                vendor_id=org_and_vendor["vendor_id"], kind="needs_human_review", reason_code="validation_failed",
                severity="warn", summary="test", details={"run_state": "needs_human_review"},
            )
        resp = await client.post(
            f"/api/v1/reviews/{esc.id}/reject", json={}, headers=_headers(org_and_vendor["org_id"])
        )
        assert resp.status_code == 200
        assert resp.json()["runState"] == "escalated_to_pm"

    async def test_request_revision_via_http(self, client, org_and_vendor, make_run):
        run_id = await make_run(state="needs_human_review", due_date=date.today())
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            esc = await entity_repo.insert_escalation(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                vendor_id=org_and_vendor["vendor_id"], kind="needs_human_review", reason_code="validation_failed",
                severity="warn", summary="test", details={"run_state": "needs_human_review"},
            )
        resp = await client.post(
            f"/api/v1/reviews/{esc.id}/request-revision",
            json={"revisionReason": "please resend with correct limits"},
            headers=_headers(org_and_vendor["org_id"]),
        )
        assert resp.status_code == 200
        assert resp.json()["runState"] == "awaiting_vendor_response"

    async def test_unknown_escalation_id_409(self, client, org_and_vendor):
        resp = await client.post(
            f"/api/v1/reviews/{uuid7()}/approve", json={}, headers=_headers(org_and_vendor["org_id"])
        )
        assert resp.status_code == 409

    async def test_resolve_escalation_via_http(self, client, org_and_vendor, make_run):
        run_id = await make_run(state="escalated_to_pm", due_date=date.today())
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            esc = await entity_repo.insert_escalation(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                vendor_id=org_and_vendor["vendor_id"], kind="escalated_to_pm", reason_code="no_response",
                severity="warn", summary="test", details={"run_state": "escalated_to_pm"},
            )
        resp = await client.post(
            f"/api/v1/escalations/{esc.id}/resolve",
            json={"decision": "resolved"},
            headers=_headers(org_and_vendor["org_id"]),
        )
        assert resp.status_code == 200
        assert resp.json()["runState"] == "monitoring"

    async def test_resolve_escalation_invalid_decision_422(self, client, org_and_vendor, make_run):
        run_id = await make_run(state="escalated_to_pm", due_date=date.today())
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            esc = await entity_repo.insert_escalation(
                conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
                vendor_id=org_and_vendor["vendor_id"], kind="escalated_to_pm", reason_code="no_response",
                severity="warn", summary="test", details={"run_state": "escalated_to_pm"},
            )
        resp = await client.post(
            f"/api/v1/escalations/{esc.id}/resolve",
            json={"decision": "not_a_real_decision"},
            headers=_headers(org_and_vendor["org_id"]),
        )
        assert resp.status_code == 422


class TestCrossOrgIsolation:
    async def test_cannot_pause_another_orgs_run(self, client, org_and_vendor, make_run):
        run_id = await make_run(state="monitoring")
        other_org_id = uuid7()
        resp = await client.post(f"/api/v1/runs/{run_id}/pause", headers=_headers(other_org_id))
        # RLS makes the run invisible under the wrong org's GUC -> treated as
        # "not found" by pause_run's _load_context, surfaced as 409 (same as
        # any other "run not found/not actionable" outcome) -- never a
        # cross-org state change.
        assert resp.status_code == 409

        # Confirm it genuinely was not paused under the real org.
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            from app.retrieval import run_repo

            run = await run_repo.get_run(conn, run_id)
        assert run.status.value == "active"
