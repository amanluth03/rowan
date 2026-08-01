"""Database session setup.

Two connection pools, matching ADR 0001's RLS shape exactly:

- `rowan_app` pool: the request-path role. Every unit of work opens a
  transaction and issues `SELECT set_config('app.current_org', <org>, true)`
  (the parameterized equivalent of `SET LOCAL app.current_org = '<uuid>'`) as
  its first statement, deriving the org from context the caller already
  authenticated (verified JWT at the API edge, or a resolved
  reply_token/run at the webhook/scheduler edge). RLS then scopes every
  query in that transaction to that org — no query in this codebase should
  ever need to say `WHERE organization_id = ...` for tenant isolation itself
  (it's still fine/expected in indexes and defense-in-depth, but isolation
  correctness must not depend on someone remembering the WHERE clause).

- `rowan_system` pool: used ONLY for the scheduler's org-enumeration query
  (`SELECT id FROM organizations WHERE agent_enabled`) plus the narrow,
  column-restricted pre-GUC lookups added in 0012_auth_grants.sql (resolving
  a verified JWT's principal on `users`, and an invitation `token_hash` on
  `invitations`). Nothing else is reachable through this pool — table-level
  GRANTs enforce that even if application code tries.

Every `tenant_isolation` policy's predicate (0008_rls.sql, amended by
0013_rls_predicate_nullif.sql) wraps the GUC read as
`nullif(current_setting('app.current_org', true), '')::uuid` rather than
casting `current_setting(...)` directly. This matters because Postgres
placeholder GUCs like `app.current_org` only return NULL from
`current_setting(name, true)` if the session has NEVER touched that name —
once `org_scoped_tx` below runs `set_config(..., true)` inside a
transaction, the value reverts to `''` (not NULL) when that transaction
ends, permanently, for the life of that physical (pooled) connection; even
an explicit `RESET` does not bring it back to NULL. Casting `''` straight
to `::uuid` raises instead of comparing against NULL. `nullif(..., '')`
collapses `''` back to NULL before the cast, so the "GUC not set" case
behaves identically whether this is a fresh connection or a reused one that
previously ran `org_scoped_tx` for a different org — see
0013_rls_predicate_nullif.sql for the full account.

# ASSUMPTION: pool sizing (min/max) is a placeholder for v1 traffic (single
demo org, low concurrency); revisit before real multi-tenant load.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import UUID

import asyncpg

from app.config import settings

_app_pool: asyncpg.Pool | None = None
_system_pool: asyncpg.Pool | None = None


async def init_pools() -> None:
    global _app_pool, _system_pool
    if _app_pool is None:
        _app_pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=10)
    if _system_pool is None:
        _system_pool = await asyncpg.create_pool(
            settings.system_database_url, min_size=1, max_size=2
        )


async def close_pools() -> None:
    global _app_pool, _system_pool
    if _app_pool is not None:
        await _app_pool.close()
        _app_pool = None
    if _system_pool is not None:
        await _system_pool.close()
        _system_pool = None


def app_pool() -> asyncpg.Pool:
    if _app_pool is None:
        raise RuntimeError("DB pools not initialized; call init_pools() at startup")
    return _app_pool


def system_pool() -> asyncpg.Pool:
    if _system_pool is None:
        raise RuntimeError("DB pools not initialized; call init_pools() at startup")
    return _system_pool


@asynccontextmanager
async def org_scoped_tx(organization_id: UUID) -> AsyncIterator[asyncpg.Connection]:
    """The one place in the codebase that opens an RLS-scoped transaction.

    Every retrieval/tool call that touches Postgres must go through this (or
    an equivalent that also sets the GUC) — never acquire a raw connection
    from app_pool() and query it directly, or RLS scoping silently no-ops
    (current_setting(..., true), collapsed through nullif(..., '') in the
    tenant_isolation predicate, reads as NULL whether the GUC was never set
    on this connection or was set-and-reverted by a prior org_scoped_tx use,
    so tenant_isolation matches nothing either way — the failure mode is
    "sees zero rows", not "leaks other orgs" or "raises" — but it's still a
    correctness bug, not a security one, given `force row level security`).
    """
    pool = app_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "select set_config('app.current_org', $1, true)", str(organization_id)
            )
            yield conn


@asynccontextmanager
async def system_conn() -> AsyncIterator[asyncpg.Connection]:
    """Connection for the narrow rowan_system role (org enumeration only)."""
    pool = system_pool()
    async with pool.acquire() as conn:
        yield conn
