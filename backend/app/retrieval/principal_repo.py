"""Layer 4 (Retrieval): resolve a verified Supabase subject to the Rowan
user/org/role it maps to.

This is the ONE lookup that cannot go through org_scoped_tx, because it is
what determines the org that org_scoped_tx would be scoped to. It therefore
uses the narrow rowan_system connection and the column-restricted grant from
migration 0012 -- exactly the pattern 0008_rls.sql established for the
webhook's reply_token resolution.

Read-only by construction: rowan_system holds no write grant on `users`.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.db import system_conn
from app.models.enums import UserRole


@dataclass(frozen=True)
class PrincipalRow:
    user_id: UUID
    organization_id: UUID
    role: UserRole


async def resolve_principal(auth_user_id: UUID) -> PrincipalRow | None:
    """Deliberately does NOT select `email`.

    rowan_system reads with `using (true)` -- cross-org by design, because
    this lookup happens before any org is known. Granting it `email` would
    make every user's address in every org readable by the role for no
    functional gain: the verified JWT already carries the caller's email.
    Least privilege (CLAUDE.md) says take the claim, not the column.
    """
    async with system_conn() as conn:
        row = await conn.fetchrow(
            "select id, organization_id, role from users where auth_user_id = $1",
            auth_user_id,
        )
    if row is None:
        return None
    return PrincipalRow(
        user_id=row["id"],
        organization_id=row["organization_id"],
        role=UserRole(row["role"]),
    )
