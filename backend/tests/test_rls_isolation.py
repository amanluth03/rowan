"""Acceptance criterion 2, database layer: one org's rows are invisible and
unwritable from another org's RLS scope.

The catalog test is the durable guard -- it is derived from pg_catalog
rather than a hardcoded table list, so ANY future table added without RLS
fails the build. `invitations` is the first new table it must cover.
"""

from __future__ import annotations

import pytest

from app.db import app_pool, org_scoped_tx
from app.ids import uuid7

pytestmark = pytest.mark.asyncio

# organizations is keyed on its own id; every other tenant table on
# organization_id (0008_rls.sql).
_EXEMPT_FROM_ORG_ID_POLICY = {"organizations"}


async def test_every_tenant_table_forces_rls(admin_conn):
    rows = await admin_conn.fetch(
        """
        select c.relname, c.relrowsecurity, c.relforcerowsecurity
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public'
          and c.relkind = 'r'
          and c.relname not in ('schema_migrations')
        """
    )
    assert rows, "expected tenant tables in the public schema"
    offenders = [
        r["relname"]
        for r in rows
        if not (r["relrowsecurity"] and r["relforcerowsecurity"])
    ]
    assert offenders == [], f"tables missing ENABLE/FORCE row level security: {offenders}"


async def test_every_tenant_table_has_tenant_isolation_policy(admin_conn):
    rows = await admin_conn.fetch(
        """
        select c.relname
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public'
          and c.relkind = 'r'
          and c.relname not in ('schema_migrations')
          and not exists (
              select 1 from pg_policy p
              where p.polrelid = c.oid and p.polname = 'tenant_isolation'
          )
        """
    )
    offenders = [r["relname"] for r in rows]
    assert offenders == [], f"tables missing a tenant_isolation policy: {offenders}"


async def test_invitations_are_invisible_across_orgs(admin_conn):
    org_a, org_b = uuid7(), uuid7()
    for org in (org_a, org_b):
        await admin_conn.execute(
            "insert into organizations (id, name, agent_enabled) values ($1,$2,true)",
            org, f"Org {org}",
        )
    invite_id = uuid7()
    await admin_conn.execute(
        """
        insert into invitations (id, organization_id, email, role, token_hash, expires_at)
        values ($1,$2,'invitee@example.com','assistant',$3, now() + interval '7 days')
        """,
        # token_hash is GLOBALLY unique, not per-org. A literal here collides
        # with itself on the second run against a persistent DB -- exactly the
        # trap backend/README.md's "Test isolation gotcha" section warns about.
        invite_id, org_a, f"hash_{invite_id}",
    )

    async with org_scoped_tx(org_b) as conn:
        assert await conn.fetchval("select count(*) from invitations where id = $1", invite_id) == 0
        assert (
            await conn.execute("update invitations set email = 'x@example.com' where id = $1", invite_id)
        ) == "UPDATE 0"
        assert (await conn.execute("delete from invitations where id = $1", invite_id)) == "DELETE 0"

    async with org_scoped_tx(org_a) as conn:
        assert await conn.fetchval("select count(*) from invitations where id = $1", invite_id) == 1


async def test_tenant_isolation_policies_use_nullif(admin_conn):
    """Pins 0013_rls_predicate_nullif.sql's fix at the catalog level: every
    tenant_isolation policy's using AND with check expression must guard
    the GUC read with NULLIF(..., ''), or it silently reintroduces
    0008_rls.sql's original predicate (which raises
    InvalidTextRepresentationError instead of matching zero rows on a
    pooled connection that already ran org_scoped_tx for a different org --
    see 0013 and app/db.py's module docstring for the full mechanism).
    Derived from pg_policy so a future migration that adds a table with the
    un-nullif'd predicate fails the build, not just a manual audit."""
    rows = await admin_conn.fetch(
        """
        select c.relname,
               pg_get_expr(p.polqual, p.polrelid) as using_expr,
               pg_get_expr(p.polwithcheck, p.polrelid) as check_expr
        from pg_policy p
        join pg_class c on c.oid = p.polrelid
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public'
          and p.polname = 'tenant_isolation'
        """
    )
    assert rows, "expected tenant_isolation policies in the public schema"
    offenders = [
        r["relname"]
        for r in rows
        if "NULLIF" not in (r["using_expr"] or "").upper()
        or "NULLIF" not in (r["check_expr"] or "").upper()
    ]
    assert offenders == [], f"tenant_isolation policies missing NULLIF guard: {offenders}"


async def test_org_scoped_tx_contamination_still_returns_zero_rows(admin_conn):
    """Direct pin of 0013's runtime behavior, not just the catalog shape
    above: a pooled connection that has run org_scoped_tx once for some org
    must, when later acquired raw (no GUC set) and queried on a tenant
    table, see zero rows -- not raise. Before 0013 this raised
    InvalidTextRepresentationError, because Postgres reverts a
    transaction-local set_config() on a placeholder GUC to '' (not NULL)
    once the transaction ends, and '' doesn't cast to uuid.

    Cycles through every connection the pool currently holds rather than
    assuming the very next acquire() hands back the one org_scoped_tx just
    used -- asyncpg's pool reuse order isn't a documented contract."""
    org_id = uuid7()
    await admin_conn.execute(
        "insert into organizations (id, name, agent_enabled) values ($1,$2,true)",
        org_id, f"Org {org_id}",
    )

    async with org_scoped_tx(org_id) as conn:
        await conn.fetchval("select 1")

    pool = app_pool()
    for _ in range(max(pool.get_size(), 1)):
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "select id from organizations where id = $1", org_id
            )
            assert row is None
