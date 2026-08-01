"""Escalations go to the OWNER.

Before multi-user orgs, get_primary_user_email picked the oldest user by
created_at, which was unambiguous when there was only ever one. With an
assistant in the org it silently became "whoever was inserted first" -- so
an org whose assistant row predates the owner's would have escalated to the
assistant. This pins the intended behavior.
"""

from __future__ import annotations

import pytest

from app.db import org_scoped_tx
from app.ids import uuid7
from app.retrieval import entity_repo

pytestmark = pytest.mark.asyncio


async def test_owner_is_chosen_even_when_inserted_after_an_assistant(admin_conn):
    org_id = uuid7()
    await admin_conn.execute(
        "insert into organizations (id, name, agent_enabled) values ($1,'Org',true)", org_id
    )
    # Assistant FIRST, so created_at ordering would pick the wrong row.
    await admin_conn.execute(
        "insert into users (id, organization_id, auth_user_id, email, role) "
        "values ($1,$2,$3,'assistant@example.com','assistant')",
        uuid7(), org_id, uuid7(),
    )
    await admin_conn.execute(
        "insert into users (id, organization_id, auth_user_id, email, role) "
        "values ($1,$2,$3,'owner@example.com','owner')",
        uuid7(), org_id, uuid7(),
    )

    async with org_scoped_tx(org_id) as conn:
        email = await entity_repo.get_primary_user_email(conn, org_id)
    assert email == "owner@example.com"


async def test_returns_none_when_org_has_no_owner(admin_conn):
    org_id = uuid7()
    await admin_conn.execute(
        "insert into organizations (id, name, agent_enabled) values ($1,'Org',true)", org_id
    )
    async with org_scoped_tx(org_id) as conn:
        assert await entity_repo.get_primary_user_email(conn, org_id) is None
