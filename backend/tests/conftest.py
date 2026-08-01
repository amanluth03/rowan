"""Shared test fixtures. DB-backed tests run against the local Postgres in
backend/docker-compose.yml (`docker compose up -d` + migrations applied —
see backend/README.md). Each test gets a fresh organization/vendor (random
UUIDs), so tests don't need cross-test cleanup or transaction rollback
tricks — this matters because several tools under test commit their own
transactions internally (send_email, parse_document; see their crash-safety
docstrings), so a single wrapping test transaction can't isolate them anyway.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from app.db import close_pools, init_pools
from app.ids import uuid7
from app.models.enums import PropertyType, VendorRole


def _require_db_env() -> None:
    # Fail loudly rather than silently skipping — DB tests are core to this
    # build's crash-recoverability/idempotency claims, not optional.
    if "DATABASE_URL" not in os.environ and not os.path.exists(
        os.path.join(os.path.dirname(__file__), "..", ".env")
    ):
        pytest.skip("DATABASE_URL not configured and no .env present; see backend/README.md")


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _pools():
    _require_db_env()
    await init_pools()
    yield
    await close_pools()


@pytest_asyncio.fixture
async def admin_conn():
    """Elevated connection for test setup only (creating orgs/vendors
    directly) — mirrors how migrations/seed run, never used to exercise
    RLS-scoped app code paths."""
    admin_url = os.environ.get(
        "ADMIN_DATABASE_URL", "postgresql://postgres:postgres@localhost:55432/rowan"
    )
    conn = await asyncpg.connect(admin_url)
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def org_and_vendor(admin_conn: asyncpg.Connection):
    """Fresh organization + property + vendor + a starter
    vendor_coverage_requirements line, isolated per test."""
    org_id = uuid7()
    property_id = uuid7()
    vendor_id = uuid7()
    requirement_id = uuid7()
    vcr_id = uuid7()

    await admin_conn.execute(
        "insert into organizations (id, name, agent_enabled) values ($1, $2, true)",
        org_id, f"Test Org {org_id}",
    )
    await admin_conn.execute(
        """
        insert into properties (id, organization_id, name, line1, city, state, postal_code, property_type)
        values ($1,$2,'Test Property','1 Test St','Boston','MA','02108',$3)
        """,
        property_id, org_id, PropertyType.multi_family.value,
    )
    await admin_conn.execute(
        """
        insert into vendors (id, organization_id, name, primary_email, vendor_role, status, primary_property_id)
        values ($1,$2,'Test Vendor','vendor@example.com',$3,'active',$4)
        """,
        vendor_id, org_id, VendorRole.plumber.value, property_id,
    )
    await admin_conn.execute(
        """
        insert into compliance_requirements (
            id, organization_id, jurisdiction_state, jurisdiction_city, vendor_role, coverage_type,
            min_each_occurrence, min_aggregate, requires_additional_insured,
            source_citation, last_verified_at, active
        ) values ($1,$2,'MA','Boston',$3,'general_liability',1000000,2000000,true,'test citation',now(),true)
        """,
        requirement_id, org_id, VendorRole.plumber.value,
    )
    await admin_conn.execute(
        """
        insert into vendor_coverage_requirements (
            id, organization_id, vendor_id, coverage_type, min_each_occurrence, min_aggregate,
            requires_additional_insured, source_compliance_requirement_id, confirmed_by_pm
        ) values ($1,$2,$3,'general_liability',1000000,2000000,true,$4,true)
        """,
        vcr_id, org_id, vendor_id, requirement_id,
    )
    owner_auth_user_id = uuid4()
    await admin_conn.execute(
        "insert into users (id, organization_id, auth_user_id, email, role) values ($1,$2,$3,$4,'owner')",
        uuid7(), org_id, owner_auth_user_id, "pm@example.com",
    )

    return {
        "org_id": org_id,
        "property_id": property_id,
        "vendor_id": vendor_id,
        "requirement_id": requirement_id,
        "vendor_coverage_requirement_id": vcr_id,
        "owner_auth_user_id": owner_auth_user_id,
    }


@pytest_asyncio.fixture
async def make_run(admin_conn: asyncpg.Connection, org_and_vendor):
    """Factory fixture: create a `runs` row directly (bypassing the
    orchestration layer) for tests that exercise tools/repos in isolation."""

    async def _make(**overrides):
        run_id = uuid7()
        defaults = dict(
            id=run_id,
            organization_id=org_and_vendor["org_id"],
            vendor_id=org_and_vendor["vendor_id"],
            state="monitoring",
            status="active",
            trigger="renewal_due",
            due_date=None,
            reply_token=f"tok_{run_id}",
            reply_token_expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            budget_cost_cap_cents=200,
            next_action_at=None,
            outreach_email_count=0,
            llm_call_count=0,
            cost_cents_spent=0,
            coi_document_id=None,
        )
        defaults.update(overrides)
        await admin_conn.execute(
            """
            insert into runs (
                id, organization_id, vendor_id, state, status, trigger, due_date,
                reply_token, reply_token_expires_at, budget_cost_cap_cents,
                next_action_at, outreach_email_count, llm_call_count, cost_cents_spent,
                coi_document_id
            ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
            """,
            defaults["id"], defaults["organization_id"], defaults["vendor_id"],
            defaults["state"], defaults["status"], defaults["trigger"], defaults["due_date"],
            defaults["reply_token"], defaults["reply_token_expires_at"], defaults["budget_cost_cap_cents"],
            defaults["next_action_at"], defaults["outreach_email_count"], defaults["llm_call_count"],
            defaults["cost_cents_spent"], defaults["coi_document_id"],
        )
        return run_id

    return _make


@pytest.fixture(scope="session")
def jwt_harness():
    """One ephemeral keypair for the whole session -- generating RSA keys is
    slow enough that per-test would be noticeable."""
    from tests.jwt_fixtures import JwtHarness

    return JwtHarness()


@pytest.fixture(autouse=True)
def _supabase_auth_configured(monkeypatch, jwt_harness):
    """Point every test at the in-process JWKS. autouse so no test can
    accidentally hit a real network endpoint."""
    from app.config import settings
    import app.policy.auth as auth_mod
    from tests.jwt_fixtures import TEST_AUDIENCE

    async def _fake_fetch() -> dict:
        return jwt_harness.jwks_dict()

    monkeypatch.setattr(auth_mod, "_fetch_jwks", _fake_fetch)
    monkeypatch.setattr(settings, "supabase_url", "https://test.supabase.co")
    monkeypatch.setattr(settings, "supabase_jwt_audience", TEST_AUDIENCE)
    auth_mod._jwks_cache = None
    yield
    auth_mod._jwks_cache = None


@pytest.fixture
def auth_headers(jwt_harness):
    """Build an Authorization header for a given Supabase auth_user_id."""

    def _headers(auth_user_id) -> dict:
        return {"Authorization": f"Bearer {jwt_harness.mint(auth_user_id)}"}

    return _headers


@pytest_asyncio.fixture
async def org_with_users(admin_conn, org_and_vendor):
    """Adds an assistant alongside the owner that org_and_vendor already
    creates, and surfaces both auth_user_ids for token minting."""
    org_id = org_and_vendor["org_id"]

    owner_auth_id = await admin_conn.fetchval(
        "select auth_user_id from users where organization_id = $1 and role = 'owner'", org_id
    )
    assistant_auth_id = uuid4()
    await admin_conn.execute(
        "insert into users (id, organization_id, auth_user_id, email, role) "
        "values ($1,$2,$3,$4,'assistant')",
        uuid7(), org_id, assistant_auth_id, "assistant@example.com",
    )
    return {
        **org_and_vendor,
        "owner_auth_id": owner_auth_id,
        "assistant_auth_id": assistant_auth_id,
    }
