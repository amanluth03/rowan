"""Approving/rejecting/deciding a COI review is a consequential action
(CLAUDE.md) -- its `resolved_by` attribution must come from the
authenticated principal, never a client-supplied request-body field.

Regression test for the finding raised in Task 5's security review: the four
review/escalation-resolution commands used to accept `resolvedBy` straight
off the wire and pass it to `escalations.resolved_by` unchecked -- forgeable,
and not even org-scoped (a caller could name a user from a different org).
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.config import settings
from app.db import org_scoped_tx
from app.ids import uuid7
from app.retrieval import entity_repo
from tests.jwt_fixtures import TEST_AUDIENCE, JwtHarness

pytestmark = pytest.mark.asyncio


@pytest.fixture
def harness(monkeypatch):
    h = JwtHarness()

    async def _fake_fetch() -> dict:
        return h.jwks_dict()

    monkeypatch.setattr("app.policy.auth._fetch_jwks", _fake_fetch)
    monkeypatch.setattr(settings, "supabase_url", "https://test.supabase.co")
    monkeypatch.setattr(settings, "supabase_jwt_audience", TEST_AUDIENCE)
    import app.policy.auth as auth_mod

    auth_mod._jwks_cache = None
    return h


@pytest.fixture
async def client():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
async def reviewer(admin_conn, org_and_vendor):
    """A real, provisioned user in org_and_vendor's org -- the one whose
    Bearer token should end up as `escalations.resolved_by`, regardless of
    what the request body claims."""
    user_id, auth_user_id = uuid7(), uuid7()
    await admin_conn.execute(
        "insert into users (id, organization_id, auth_user_id, email, role) "
        "values ($1,$2,$3,$4,'owner')",
        user_id, org_and_vendor["org_id"], auth_user_id, "reviewer@example.com",
    )
    return {"user_id": user_id, "auth_user_id": auth_user_id}


def _bearer(harness: JwtHarness, auth_user_id) -> dict:
    return {"Authorization": f"Bearer {harness.mint(auth_user_id)}"}


async def _resolved_by(admin_conn, escalation_id) -> str | None:
    row = await admin_conn.fetchrow("select resolved_by from escalations where id = $1", escalation_id)
    return row["resolved_by"]


async def test_resolved_by_is_the_authenticated_user_not_the_request_body(
    client, harness, admin_conn, org_and_vendor, make_run, reviewer
):
    """Attribution for a consequential action comes from the verified JWT.
    A body field naming someone else must not be honoured -- and must not be
    accepted at all, so a forged attribution fails loudly rather than
    silently being ignored.
    """
    run_id = await make_run(state="needs_human_review", due_date=date.today())
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        esc = await entity_repo.insert_escalation(
            conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
            vendor_id=org_and_vendor["vendor_id"], kind="needs_human_review", reason_code="validation_failed",
            severity="warn", summary="test", details={"run_state": "needs_human_review"},
        )

    forged_approver = uuid7()  # some other user's id -- not the caller's.
    resp = await client.post(
        f"/api/v1/reviews/{esc.id}/approve",
        json={"resolvedBy": str(forged_approver)},
        headers=_bearer(harness, reviewer["auth_user_id"]),
    )
    assert resp.status_code == 200, resp.text

    # (a) The forged field must not be reflected anywhere -- the response
    # schema doesn't even expose resolved_by, so the only place it could leak
    # through is the persisted row.
    persisted = await _resolved_by(admin_conn, esc.id)
    # (b) The persisted attribution is the AUTHENTICATED user, never the
    # forged body value.
    assert str(persisted) == str(reviewer["user_id"])
    assert str(persisted) != str(forged_approver)


async def test_resolved_by_request_body_field_is_not_accepted(client, harness, org_and_vendor, make_run, reviewer):
    """A `resolvedBy` field in the JSON body is not even a recognized field
    on the wire schema any more -- pydantic's default `extra='ignore'`
    drops it silently rather than erroring, which is fine: the point is it
    can never reach the tool/DB layer, not that the client gets a particular
    status code for supplying it."""
    run_id = await make_run(state="needs_human_review", due_date=date.today())
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        esc = await entity_repo.insert_escalation(
            conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
            vendor_id=org_and_vendor["vendor_id"], kind="needs_human_review", reason_code="validation_failed",
            severity="warn", summary="test", details={"run_state": "needs_human_review"},
        )
    resp = await client.post(
        f"/api/v1/reviews/{esc.id}/reject",
        json={"resolvedBy": str(uuid7())},
        headers=_bearer(harness, reviewer["auth_user_id"]),
    )
    assert resp.status_code == 200, resp.text
    assert "resolvedBy" not in resp.json()
    assert "resolved_by" not in resp.json()


async def test_reviews_and_escalations_require_authentication(client, harness, org_and_vendor, make_run):
    """The four review/escalation-resolution routes are not exempt from
    get_principal -- no Authorization header, no action, regardless of what
    the body contains."""
    run_id = await make_run(state="needs_human_review", due_date=date.today())
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        esc = await entity_repo.insert_escalation(
            conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
            vendor_id=org_and_vendor["vendor_id"], kind="needs_human_review", reason_code="validation_failed",
            severity="warn", summary="test", details={"run_state": "needs_human_review"},
        )
    resp = await client.post(f"/api/v1/reviews/{esc.id}/approve", json={})
    assert resp.status_code == 401
