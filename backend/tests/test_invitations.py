"""Owner invites an assistant; the assistant joins THAT org and no other.

Covers the security properties that matter: the raw token never lands in
the database, acceptance is single-use and expiring, the email is bound, and
an assistant cannot invite anyone.
"""

from __future__ import annotations

import hashlib

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


@pytest.fixture(autouse=True)
def _capture_mail(monkeypatch):
    """Capture outbound invites instead of sending. Returns the list so
    tests can read the accept_url the invitee would have received."""
    sent = []

    async def _fake_send(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr("app.orchestration.runner.send_transactional", _fake_send)
    return sent


async def test_owner_can_invite_and_token_is_never_stored(
    client, jwt_harness, org_with_users, _capture_mail
):
    resp = await client.post(
        "/api/v1/invitations",
        json={"email": "newhire@example.com"},
        headers={"Authorization": f"Bearer {jwt_harness.mint(org_with_users['owner_auth_id'])}"},
    )
    assert resp.status_code == 201, resp.text

    assert len(_capture_mail) == 1
    accept_url = _capture_mail[0]["text"]
    raw_token = accept_url.split("/accept-invite/")[1].split()[0]

    async with org_scoped_tx(org_with_users["org_id"]) as conn:
        row = await conn.fetchrow(
            "select token_hash from invitations where lower(email) = 'newhire@example.com'"
        )
    # The plaintext token exists only in the email.
    assert row["token_hash"] == hashlib.sha256(raw_token.encode()).hexdigest()
    assert raw_token not in row["token_hash"]


async def test_assistant_cannot_invite(client, jwt_harness, org_with_users):
    resp = await client.post(
        "/api/v1/invitations",
        json={"email": "nope@example.com"},
        headers={
            "Authorization": f"Bearer {jwt_harness.mint(org_with_users['assistant_auth_id'])}"
        },
    )
    assert resp.status_code == 403


async def test_accept_puts_the_user_in_the_inviting_org_as_assistant(
    client, jwt_harness, org_with_users, _capture_mail
):
    await client.post(
        "/api/v1/invitations",
        json={"email": "newhire@example.com"},
        headers={"Authorization": f"Bearer {jwt_harness.mint(org_with_users['owner_auth_id'])}"},
    )
    raw_token = _capture_mail[0]["text"].split("/accept-invite/")[1].split()[0]

    invitee_auth = uuid7()
    resp = await client.post(
        "/api/v1/invitations/accept",
        json={"token": raw_token},
        headers={
            "Authorization": f"Bearer {jwt_harness.mint(invitee_auth, email='newhire@example.com')}"
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["organizationId"] == str(org_with_users["org_id"])

    async with org_scoped_tx(org_with_users["org_id"]) as conn:
        role = await conn.fetchval(
            "select role from users where auth_user_id = $1", invitee_auth
        )
    assert role == "assistant"


async def test_accept_is_single_use(client, jwt_harness, org_with_users, _capture_mail):
    await client.post(
        "/api/v1/invitations",
        json={"email": "newhire@example.com"},
        headers={"Authorization": f"Bearer {jwt_harness.mint(org_with_users['owner_auth_id'])}"},
    )
    raw_token = _capture_mail[0]["text"].split("/accept-invite/")[1].split()[0]

    first = await client.post(
        "/api/v1/invitations/accept", json={"token": raw_token},
        headers={"Authorization": f"Bearer {jwt_harness.mint(uuid7(), email='newhire@example.com')}"},
    )
    assert first.status_code == 201
    second = await client.post(
        "/api/v1/invitations/accept", json={"token": raw_token},
        headers={"Authorization": f"Bearer {jwt_harness.mint(uuid7(), email='newhire@example.com')}"},
    )
    assert second.status_code == 400


async def test_accept_rejects_email_mismatch(
    client, jwt_harness, org_with_users, _capture_mail
):
    await client.post(
        "/api/v1/invitations",
        json={"email": "newhire@example.com"},
        headers={"Authorization": f"Bearer {jwt_harness.mint(org_with_users['owner_auth_id'])}"},
    )
    raw_token = _capture_mail[0]["text"].split("/accept-invite/")[1].split()[0]

    resp = await client.post(
        "/api/v1/invitations/accept", json={"token": raw_token},
        headers={"Authorization": f"Bearer {jwt_harness.mint(uuid7(), email='someone.else@example.com')}"},
    )
    assert resp.status_code == 400


async def test_accept_rejects_unknown_token(client, jwt_harness):
    resp = await client.post(
        "/api/v1/invitations/accept", json={"token": "not-a-real-token"},
        headers={"Authorization": f"Bearer {jwt_harness.mint(uuid7(), email='x@example.com')}"},
    )
    assert resp.status_code == 400


async def test_owner_sees_only_their_own_pending_invitations(
    client, jwt_harness, org_with_users, admin_conn, _capture_mail
):
    other_org = uuid7()
    await admin_conn.execute(
        "insert into organizations (id, name, agent_enabled) values ($1,'Other',true)", other_org
    )
    await admin_conn.execute(
        "insert into invitations (id, organization_id, email, role, token_hash, expires_at) "
        "values ($1,$2,'theirs@example.com','assistant',$3, now() + interval '7 days')",
        # Globally-unique column -- never a literal (see backend/README.md's
        # "Test isolation gotcha").
        uuid7(), other_org, f"otherhash_{uuid7()}",
    )
    await client.post(
        "/api/v1/invitations", json={"email": "mine@example.com"},
        headers={"Authorization": f"Bearer {jwt_harness.mint(org_with_users['owner_auth_id'])}"},
    )

    resp = await client.get(
        "/api/v1/invitations",
        headers={"Authorization": f"Bearer {jwt_harness.mint(org_with_users['owner_auth_id'])}"},
    )
    emails = [i["email"] for i in resp.json()]
    assert emails == ["mine@example.com"]
