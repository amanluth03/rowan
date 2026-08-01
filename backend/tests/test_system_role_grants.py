"""rowan_system may resolve a principal and an invite token across orgs
WITHOUT app.current_org set -- the same narrow, single-purpose mechanism
0008_rls.sql already uses for the webhook's reply_token resolution.

Also asserts the negative: rowan_app cannot do these lookups, so the
privilege genuinely lives in the narrow role and not the broad one.
"""

from __future__ import annotations

import asyncpg
import pytest

from app.db import app_pool, system_conn
from app.ids import uuid7

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def seeded(admin_conn):
    org_id, user_id, invite_id = uuid7(), uuid7(), uuid7()
    auth_user_id = uuid7()
    await admin_conn.execute(
        "insert into organizations (id, name, agent_enabled) values ($1,$2,true)",
        org_id, f"Org {org_id}",
    )
    await admin_conn.execute(
        "insert into users (id, organization_id, auth_user_id, email, role) "
        "values ($1,$2,$3,$4,'owner')",
        user_id, org_id, auth_user_id, "owner@example.com",
    )
    await admin_conn.execute(
        "insert into invitations (id, organization_id, email, role, token_hash, expires_at) "
        "values ($1,$2,'invitee@example.com','assistant',$3, now() + interval '7 days')",
        invite_id, org_id, f"hash_{invite_id}",
    )
    return {
        "org_id": org_id, "user_id": user_id,
        "auth_user_id": auth_user_id, "invite_id": invite_id,
        "token_hash": f"hash_{invite_id}",
    }


async def test_system_resolves_principal_without_guc(seeded):
    async with system_conn() as conn:
        row = await conn.fetchrow(
            "select id, organization_id, auth_user_id, role from users where auth_user_id = $1",
            seeded["auth_user_id"],
        )
    assert row is not None
    assert row["organization_id"] == seeded["org_id"]
    assert row["role"] == "owner"


async def test_system_resolves_invitation_without_guc(seeded):
    async with system_conn() as conn:
        row = await conn.fetchrow(
            "select id, organization_id, role, expires_at, accepted_at "
            "from invitations where token_hash = $1",
            seeded["token_hash"],
        )
    assert row is not None
    assert row["organization_id"] == seeded["org_id"]


async def test_system_cannot_read_user_emails(seeded):
    """users.email is deliberately NOT granted -- the JWT claim supplies it."""
    async with system_conn() as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetchval(
                "select email from users where auth_user_id = $1", seeded["auth_user_id"]
            )


async def test_app_role_cannot_resolve_principal_without_guc(seeded):
    # rowan_app has no cross-org visibility: with the GUC unset the
    # tenant_isolation policy matches nothing, so this returns zero rows.
    async with app_pool().acquire() as conn:
        row = await conn.fetchrow(
            "select id from users where auth_user_id = $1", seeded["auth_user_id"]
        )
    assert row is None
