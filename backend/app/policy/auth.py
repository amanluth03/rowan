"""Layer 5 (Policy): Supabase JWT verification.

Deliberately knows nothing about FastAPI, the database, or Rowan's own
`users` table -- it answers exactly one question ("is this a live, valid
token from our Supabase project, and whose?"). Mapping a verified `sub` to
a Rowan organization is a separate concern, in app/retrieval/principal_repo.py.

Fails closed at every branch: an unconfigured project, an unfetchable JWKS,
an unknown key id, a disallowed algorithm, a bad issuer/audience, an expired
token, and a non-UUID subject all raise InvalidTokenError. There is no code
path that returns a Claims object without a verified signature.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import UUID

import httpx
import jwt

from app.config import settings

# Explicit allowlist. NEVER trust the token header's `alg` -- accepting
# whatever it claims is the `alg: none` and HS256-confusion bypass.
_ALLOWED_ALGORITHMS = ("RS256", "ES256")

_jwks_cache: tuple[float, dict] | None = None


class InvalidTokenError(Exception):
    """Raised for every verification failure. Callers map this to 401 and
    must never distinguish the reasons to the client -- doing so tells an
    attacker which half of a forgery attempt worked."""


@dataclass(frozen=True)
class Claims:
    sub: UUID
    email: str | None


async def _fetch_jwks() -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(settings.resolved_jwks_url)
        resp.raise_for_status()
        return resp.json()


async def _jwks() -> dict:
    global _jwks_cache
    now = time.monotonic()
    if _jwks_cache is not None:
        fetched_at, doc = _jwks_cache
        if now - fetched_at < settings.supabase_jwks_cache_seconds:
            return doc
    # Look up _fetch_jwks via the module namespace (not a bound local
    # reference) so tests can monkeypatch it with
    # `monkeypatch.setattr("app.policy.auth._fetch_jwks", ...)` and have
    # this call site actually pick up the replacement.
    doc = await _fetch_jwks()
    _jwks_cache = (now, doc)
    return doc


async def verify_supabase_jwt(token: str) -> Claims:
    if not settings.supabase_url and not settings.supabase_jwks_url:
        raise InvalidTokenError("Supabase auth is not configured")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise InvalidTokenError("malformed token") from e

    if header.get("alg") not in _ALLOWED_ALGORITHMS:
        raise InvalidTokenError("disallowed signing algorithm")

    kid = header.get("kid")
    if not kid:
        raise InvalidTokenError("token has no key id")

    try:
        jwk_set = jwt.PyJWKSet.from_dict(await _jwks())
    except Exception as e:
        raise InvalidTokenError("could not load signing keys") from e

    signing_key = next((k for k in jwk_set.keys if k.key_id == kid), None)
    if signing_key is None:
        raise InvalidTokenError("unknown key id")

    try:
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=list(_ALLOWED_ALGORITHMS),
            audience=settings.supabase_jwt_audience,
            issuer=settings.resolved_jwt_issuer,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.PyJWTError as e:
        raise InvalidTokenError("token verification failed") from e

    try:
        sub = UUID(payload["sub"])
    except (KeyError, ValueError, TypeError) as e:
        raise InvalidTokenError("token subject is not a UUID") from e

    return Claims(sub=sub, email=payload.get("email"))
