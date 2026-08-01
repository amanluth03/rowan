"""Signup: a verified Supabase user with no Rowan org creates one and
becomes its owner.

This is the only write in the system that cannot be org-scoped on entry --
the org does not exist yet. It is nonetheless performed by rowan_app under
normal RLS, because we mint the org id app-side and set app.current_org to
it before inserting (see runner.bootstrap_organization).
"""

from __future__ import annotations

import httpx
import pytest

from app.db import org_scoped_tx
from app.ids import uuid7

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def client():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def test_bootstrap_creates_org_and_owner(client, jwt_harness):
    auth_id = uuid7()
    resp = await client.post(
        "/api/v1/orgs/bootstrap",
        json={"organizationName": "Dana PM LLC", "fullName": "Dana Rivera"},
        headers={"Authorization": f"Bearer {jwt_harness.mint(auth_id, email='dana@example.com')}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    org_id = body["organizationId"]

    async with org_scoped_tx(org_id) as conn:
        row = await conn.fetchrow(
            "select email, role, organization_id from users where auth_user_id = $1", auth_id
        )
    assert row["role"] == "owner"
    assert row["email"] == "dana@example.com"
    assert str(row["organization_id"]) == org_id


async def test_bootstrap_is_idempotent_per_auth_user(client, jwt_harness):
    auth_id = uuid7()
    headers = {"Authorization": f"Bearer {jwt_harness.mint(auth_id)}"}
    first = await client.post(
        "/api/v1/orgs/bootstrap", json={"organizationName": "First"}, headers=headers
    )
    assert first.status_code == 201
    second = await client.post(
        "/api/v1/orgs/bootstrap", json={"organizationName": "Second"}, headers=headers
    )
    assert second.status_code == 409, second.text


async def test_bootstrap_requires_a_valid_token(client):
    resp = await client.post("/api/v1/orgs/bootstrap", json={"organizationName": "X"})
    assert resp.status_code == 401


async def test_bootstrap_rejects_forged_token(client, jwt_harness):
    resp = await client.post(
        "/api/v1/orgs/bootstrap",
        json={"organizationName": "X"},
        headers={"Authorization": f"Bearer {jwt_harness.mint_unsigned(uuid7())}"},
    )
    assert resp.status_code == 401


async def test_bootstrapped_org_is_isolated(client, jwt_harness):
    """Two fresh signups must not see each other -- the end-to-end shape of
    acceptance criterion 2."""
    a_auth, b_auth = uuid7(), uuid7()
    a = await client.post(
        "/api/v1/orgs/bootstrap", json={"organizationName": "Org A"},
        headers={"Authorization": f"Bearer {jwt_harness.mint(a_auth)}"},
    )
    await client.post(
        "/api/v1/orgs/bootstrap", json={"organizationName": "Org B"},
        headers={"Authorization": f"Bearer {jwt_harness.mint(b_auth)}"},
    )

    await client.post(
        "/api/v1/vendors",
        json={"name": "A's Vendor", "primaryEmail": "v@a.example.com", "vendorRole": "plumber"},
        headers={"Authorization": f"Bearer {jwt_harness.mint(a_auth)}"},
    )

    b_vendors = await client.get(
        "/api/v1/vendors", headers={"Authorization": f"Bearer {jwt_harness.mint(b_auth)}"}
    )
    assert b_vendors.status_code == 200
    assert b_vendors.json() == []

    a_vendors = await client.get(
        "/api/v1/vendors", headers={"Authorization": f"Bearer {jwt_harness.mint(a_auth)}"}
    )
    assert len(a_vendors.json()) == 1
