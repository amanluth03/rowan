"""The user_role vocabulary is exactly {owner, assistant} in both Python and
Postgres. Guards against the two drifting apart (a rename applied in one
place only would silently break role checks at the DB boundary)."""

from __future__ import annotations

import pytest

from app.models.enums import UserRole

pytestmark = pytest.mark.asyncio


def test_python_enum_values():
    assert {r.value for r in UserRole} == {"owner", "assistant"}
    assert not hasattr(UserRole, "pm")


async def test_postgres_enum_matches_python(admin_conn):
    rows = await admin_conn.fetch(
        "select unnest(enum_range(null::user_role))::text as value"
    )
    assert {r["value"] for r in rows} == {r.value for r in UserRole}
