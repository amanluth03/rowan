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

# Tables that hold GLOBAL REFERENCE DATA — the same rows for every customer,
# belonging to no organization. These correctly have no `organization_id` and
# therefore no `tenant_isolation` policy.
#
# ADDING TO THIS SET IS A SECURITY DECISION, not a way to make a red test go
# green. A table belongs here ONLY if all three hold:
#
#   1. It has no `organization_id` column and never will.
#   2. Every organization is meant to read identical rows from it.
#   3. Request-path code has SELECT only — writes happen via migrations or an
#      admin path, never as `rowan_app` on behalf of a user.
#
# If any of those is false the table is tenant data and needs RLS. When in
# doubt, it needs RLS: the failure mode of a wrong exemption is silent
# cross-tenant disclosure, and no test will catch it afterwards.
#
# `test_reference_tables_are_genuinely_global` below enforces (1) and (3)
# mechanically, so a tenant table cannot be smuggled in by adding its name.
_GLOBAL_REFERENCE_TABLES = {
    # Compliance knowledge base (0015/0016) — jurisdictions and the
    # obligations attached to them. City rules are identical for every
    # customer; `rowan_app` holds SELECT only.
    "compliance_jurisdictions",
    "compliance_obligations",
}

_NOT_TENANT_TABLES = {"schema_migrations"} | _GLOBAL_REFERENCE_TABLES


async def test_every_tenant_table_forces_rls(admin_conn):
    rows = await admin_conn.fetch(
        """
        select c.relname, c.relrowsecurity, c.relforcerowsecurity
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public'
          and c.relkind = 'r'
          and c.relname != all($1::text[])
        """,
        sorted(_NOT_TENANT_TABLES),
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
          and c.relname != all($1::text[])
          and not exists (
              select 1 from pg_policy p
              where p.polrelid = c.oid and p.polname = 'tenant_isolation'
          )
        """,
        sorted(_NOT_TENANT_TABLES),
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


async def test_reference_tables_are_genuinely_global(admin_conn):
    """The exemption list in _GLOBAL_REFERENCE_TABLES cannot be used to
    smuggle a tenant table past the two guards above.

    Adding a name to that set is otherwise a one-line way to silence a red
    RLS test forever, and the failure mode -- a tenant table readable across
    organizations -- produces no symptom until a customer sees another
    customer's data. So the exemption is checked mechanically rather than
    trusted:

      1. no `organization_id` column (if it has one, it is tenant data), and
      2. `rowan_app` holds SELECT only (no INSERT/UPDATE/DELETE), so
         request-path code cannot write to it on a user's behalf.
    """
    for table in sorted(_GLOBAL_REFERENCE_TABLES):
        exists = await admin_conn.fetchval(
            "select to_regclass($1) is not null", f"public.{table}"
        )
        assert exists, (
            f"{table} is exempted from RLS but does not exist -- remove the "
            f"stale entry from _GLOBAL_REFERENCE_TABLES"
        )

        has_org_col = await admin_conn.fetchval(
            """
            select exists (
                select 1 from information_schema.columns
                where table_schema = 'public'
                  and table_name = $1
                  and column_name = 'organization_id'
            )
            """,
            table,
        )
        assert not has_org_col, (
            f"{table} has an organization_id column, so it is TENANT DATA and "
            f"must have RLS + a tenant_isolation policy. Remove it from "
            f"_GLOBAL_REFERENCE_TABLES and add the policy."
        )

        writes = await admin_conn.fetch(
            """
            select privilege_type
            from information_schema.role_table_grants
            where table_schema = 'public'
              and table_name = $1
              and grantee = 'rowan_app'
              and privilege_type in ('INSERT', 'UPDATE', 'DELETE')
            """,
            table,
        )
        assert writes == [], (
            f"{table} is exempted from RLS but grants rowan_app "
            f"{[w['privilege_type'] for w in writes]}. Request-path code can "
            f"write to it with no tenant scoping. Either drop the write grants "
            f"(reference data is migration-managed) or treat it as tenant data."
        )
