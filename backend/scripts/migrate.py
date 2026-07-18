"""Apply SQL migrations in backend/migrations/ in filename order.

Tracks applied migrations in a `schema_migrations` table. Connects with an
admin/superuser-equivalent DSN (ADMIN_DATABASE_URL) — never the request-path
`rowan_app` role — matching ADR 0001's rule that the elevated credential is
only ever used from migrations/seed, never request-path code.

Usage:
    uv run python scripts/migrate.py                # apply all pending
    uv run python scripts/migrate.py --dry-run       # list pending only

Required env vars (see backend/.env.example):
    ADMIN_DATABASE_URL          - postgres DSN with rights to CREATE ROLE /
                                   ALTER TABLE ... FORCE ROW LEVEL SECURITY.
    ROWAN_APP_DB_PASSWORD       - password to assign to the rowan_app role
                                   (0008_rls.sql), read via a session GUC so
                                   it never appears in the SQL file itself.
    ROWAN_SYSTEM_DB_PASSWORD    - password to assign to the rowan_system role.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


async def _ensure_tracking_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        create table if not exists schema_migrations (
            filename text primary key,
            applied_at timestamptz not null default now()
        )
        """
    )


async def _applied(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch("select filename from schema_migrations")
    return {r["filename"] for r in rows}


async def run(dry_run: bool = False) -> None:
    admin_url = os.environ["ADMIN_DATABASE_URL"]
    app_password = os.environ.get("ROWAN_APP_DB_PASSWORD", "rowan_app_dev_password")
    system_password = os.environ.get("ROWAN_SYSTEM_DB_PASSWORD", "rowan_system_dev_password")

    conn = await asyncpg.connect(admin_url)
    try:
        await _ensure_tracking_table(conn)
        applied = await _applied(conn)

        files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        pending = [f for f in files if f.name not in applied]

        if not pending:
            print("No pending migrations.")
            return

        for f in pending:
            print(f"{'[dry-run] would apply' if dry_run else 'Applying'}: {f.name}")
            if dry_run:
                continue

            # Custom session GUCs used by 0008_rls.sql to set role passwords
            # without hardcoding a secret in the SQL file. Plain SET (not SET
            # LOCAL) so it survives across the statements in this connection.
            # set_config avoids string-interpolating the secret into SQL text.
            await conn.execute(
                "select set_config('rowan.migrate_app_password', $1, false)", app_password
            )
            await conn.execute(
                "select set_config('rowan.migrate_system_password', $1, false)", system_password
            )

            sql = f.read_text()
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "insert into schema_migrations(filename) values ($1)", f.name
                )

        if not dry_run:
            print(f"Applied {len(pending)} migration(s).")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run(dry_run="--dry-run" in sys.argv))
