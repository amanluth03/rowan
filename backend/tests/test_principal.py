"""auth_user_id -> Principal resolution, and the HTTP dependency around it."""

from __future__ import annotations

import httpx
import pytest

from app.config import settings
from app.ids import uuid7
from app.models.enums import UserRole
from app.retrieval.principal_repo import resolve_principal
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
async def owner(admin_conn):
    org_id, user_id, auth_user_id = uuid7(), uuid7(), uuid7()
    await admin_conn.execute(
        "insert into organizations (id, name, agent_enabled) values ($1,$2,true)",
        org_id, f"Org {org_id}",
    )
    await admin_conn.execute(
        "insert into users (id, organization_id, auth_user_id, email, role) "
        "values ($1,$2,$3,$4,'owner')",
        user_id, org_id, auth_user_id, "owner@example.com",
    )
    return {"org_id": org_id, "user_id": user_id, "auth_user_id": auth_user_id}


@pytest.fixture
async def client():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def test_resolve_principal_returns_org_and_role(owner):
    row = await resolve_principal(owner["auth_user_id"])
    assert row is not None
    assert row.organization_id == owner["org_id"]
    assert row.user_id == owner["user_id"]
    assert row.role is UserRole.owner


async def test_resolve_principal_unknown_returns_none():
    assert await resolve_principal(uuid7()) is None


async def test_bearer_token_authenticates_request(client, harness, owner):
    resp = await client.get(
        "/api/v1/vendors",
        headers={"Authorization": f"Bearer {harness.mint(owner['auth_user_id'])}"},
    )
    assert resp.status_code == 200, resp.text


async def test_no_authorization_header_is_401(client, harness):
    assert (await client.get("/api/v1/vendors")).status_code == 401


async def test_valid_token_unknown_user_is_401(client, harness):
    # Signed correctly, but never provisioned into a Rowan org.
    resp = await client.get(
        "/api/v1/vendors",
        headers={"Authorization": f"Bearer {harness.mint(uuid7())}"},
    )
    assert resp.status_code == 401


async def test_legacy_org_header_is_ignored(client, harness, owner):
    # The dev stub is GONE. Supplying it must not authenticate anything --
    # if this ever returns 200, the bypass is back.
    resp = await client.get("/api/v1/vendors", headers={"X-Rowan-Org-Id": str(owner["org_id"])})
    assert resp.status_code == 401
