"""Layer 4 (Retrieval): invitation records.

Two access paths, deliberately different:

  - Org-scoped (create/list/revoke) go through org_scoped_tx as normal --
    the caller is an authenticated owner and their org is known.
  - Token resolution goes through the narrow rowan_system connection,
    because the invitee has no org yet. Same pre-GUC pattern as
    principal_repo, and the same one 0008_rls.sql uses for reply_token.

The raw token is never persisted. We store sha256(token); the plaintext
exists only in the invite email.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg

from app.db import org_scoped_tx, system_conn
from app.ids import uuid7
from app.models.enums import UserRole

# # ASSUMPTION: 7-day expiry pending real Dana input.
INVITE_VALIDITY_DAYS = 7


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


@dataclass(frozen=True)
class InvitationRow:
    id: UUID
    organization_id: UUID
    email: str
    role: UserRole
    expires_at: datetime
    accepted_at: datetime | None


async def create_invitation(
    organization_id: UUID, email: str, role: UserRole, invited_by_user_id: UUID
) -> tuple[UUID, str]:
    """Returns (invitation_id, raw_token). The raw token is returned ONCE
    and never retrievable again."""
    raw_token = secrets.token_urlsafe(32)
    invitation_id = uuid7()
    expires_at = datetime.now(timezone.utc) + timedelta(days=INVITE_VALIDITY_DAYS)

    async with org_scoped_tx(organization_id) as conn:
        try:
            await conn.execute(
                """
                insert into invitations
                    (id, organization_id, email, role, token_hash, invited_by_user_id, expires_at)
                values ($1,$2,$3,$4,$5,$6,$7)
                """,
                invitation_id, organization_id, email, role.value,
                hash_token(raw_token), invited_by_user_id, expires_at,
            )
        except asyncpg.UniqueViolationError as e:
            raise ValueError("an invitation is already pending for this email") from e

    return invitation_id, raw_token


async def resolve_invitation_by_token(raw_token: str) -> InvitationRow | None:
    """Cross-org, pre-GUC lookup via rowan_system -- the invitee has no org
    yet, so there is nothing to scope to. SELECT-only by grant."""
    async with system_conn() as conn:
        row = await conn.fetchrow(
            """
            select id, organization_id, email, role, expires_at, accepted_at
            from invitations where token_hash = $1
            """,
            hash_token(raw_token),
        )
    if row is None:
        return None
    return InvitationRow(
        id=row["id"],
        organization_id=row["organization_id"],
        email=row["email"],
        role=UserRole(row["role"]),
        expires_at=row["expires_at"],
        accepted_at=row["accepted_at"],
    )


async def list_pending(organization_id: UUID) -> list[InvitationRow]:
    async with org_scoped_tx(organization_id) as conn:
        rows = await conn.fetch(
            """
            select id, organization_id, email, role, expires_at, accepted_at
            from invitations where accepted_at is null order by created_at desc
            """
        )
    return [
        InvitationRow(
            id=r["id"], organization_id=r["organization_id"], email=r["email"],
            role=UserRole(r["role"]), expires_at=r["expires_at"], accepted_at=r["accepted_at"],
        )
        for r in rows
    ]


async def revoke(organization_id: UUID, invitation_id: UUID) -> bool:
    async with org_scoped_tx(organization_id) as conn:
        result = await conn.execute(
            "delete from invitations where id = $1 and accepted_at is null", invitation_id
        )
    return result != "DELETE 0"
