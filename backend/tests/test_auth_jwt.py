"""verify_supabase_jwt accepts exactly one thing: a live, correctly-signed,
correctly-scoped token from our project. Everything else fails closed."""

from __future__ import annotations

import pytest

from app.config import settings
from app.policy.auth import InvalidTokenError, verify_supabase_jwt
from tests.jwt_fixtures import TEST_AUDIENCE, TEST_ISSUER, JwtHarness

pytestmark = pytest.mark.asyncio


@pytest.fixture
def harness(monkeypatch):
    h = JwtHarness()

    async def _fake_fetch() -> dict:
        return h.jwks_dict()

    monkeypatch.setattr("app.policy.auth._fetch_jwks", _fake_fetch)
    monkeypatch.setattr(settings, "supabase_url", "https://test.supabase.co")
    monkeypatch.setattr(settings, "supabase_jwt_audience", TEST_AUDIENCE)
    import app.policy.auth as auth_mod
    auth_mod._jwks_cache = None
    return h


async def test_valid_token_yields_claims(harness):
    from app.ids import uuid7
    sub = uuid7()
    claims = await verify_supabase_jwt(harness.mint(sub, email="dana@example.com"))
    assert claims.sub == sub
    assert claims.email == "dana@example.com"


async def test_expired_token_rejected(harness):
    from app.ids import uuid7
    with pytest.raises(InvalidTokenError):
        await verify_supabase_jwt(harness.mint(uuid7(), expires_in=-60))


async def test_wrong_issuer_rejected(harness):
    from app.ids import uuid7
    with pytest.raises(InvalidTokenError):
        await verify_supabase_jwt(harness.mint(uuid7(), issuer="https://evil.example.com/auth/v1"))


async def test_wrong_audience_rejected(harness):
    from app.ids import uuid7
    with pytest.raises(InvalidTokenError):
        await verify_supabase_jwt(harness.mint(uuid7(), audience="anon"))


async def test_alg_none_rejected(harness):
    from app.ids import uuid7
    with pytest.raises(InvalidTokenError):
        await verify_supabase_jwt(harness.mint_unsigned(uuid7()))


async def test_unknown_kid_rejected(harness):
    from app.ids import uuid7
    with pytest.raises(InvalidTokenError):
        await verify_supabase_jwt(harness.mint(uuid7(), kid="attacker-key"))


async def test_garbage_rejected(harness):
    with pytest.raises(InvalidTokenError):
        await verify_supabase_jwt("not-a-jwt")


async def test_non_uuid_sub_rejected(harness):
    with pytest.raises(InvalidTokenError):
        await verify_supabase_jwt(harness.mint("not-a-uuid"))


async def test_unconfigured_supabase_fails_closed(harness, monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_jwks_url", "")
    from app.ids import uuid7
    with pytest.raises(InvalidTokenError):
        await verify_supabase_jwt(harness.mint(uuid7()))
