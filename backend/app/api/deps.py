"""Interface-layer (layer 1) shared dependencies: authentication,
authorization, and rate limiting.

Every route in app/api/ derives its `organization_id` from a VERIFIED
Supabase JWT -- never from a client-supplied body, query, or header field.
The dev-mode `X-Rowan-Org-Id` stub that used to live here is GONE, with no
fallback: a fallback would be a bypass.

Resolution order, all fail-closed:
    Authorization: Bearer <jwt>
      -> app.policy.auth.verify_supabase_jwt   (signature, iss, aud, exp)
      -> app.retrieval.principal_repo.resolve_principal  (sub -> org + role)
      -> Principal
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request

from app.models.enums import UserRole
from app.policy.auth import InvalidTokenError, verify_supabase_jwt
from app.policy.rate_limit import RateLimiter
from app.retrieval.principal_repo import resolve_principal


@dataclass(frozen=True)
class Principal:
    """Who is making this request, and on whose behalf. Frozen so a handler
    cannot mutate its own authorization mid-request."""

    user_id: UUID
    auth_user_id: UUID
    organization_id: UUID
    role: UserRole
    # Sourced from the verified JWT claim, NOT from the users table --
    # rowan_system is deliberately not granted users.email (see
    # principal_repo.resolve_principal).
    email: str


def _unauthorized() -> HTTPException:
    # One generic message for every failure mode. Distinguishing "bad
    # signature" from "unknown user" tells an attacker which half of a
    # forgery attempt succeeded.
    return HTTPException(
        status_code=401,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_principal(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized()

    token = authorization[7:].strip()
    if not token:
        raise _unauthorized()

    try:
        claims = await verify_supabase_jwt(token)
    except InvalidTokenError as e:
        raise _unauthorized() from e

    row = await resolve_principal(claims.sub)
    if row is None:
        # Authenticated with Supabase but not provisioned into a Rowan org
        # (e.g. signed up but never completed bootstrap). Not an error the
        # client can exploit; the signup flow handles it explicitly.
        raise _unauthorized()

    return Principal(
        user_id=row.user_id,
        auth_user_id=claims.sub,
        organization_id=row.organization_id,
        role=row.role,
        # From the VERIFIED claim, not from the users table -- see
        # resolve_principal's docstring on why rowan_system is not granted
        # the email column.
        email=claims.email or "",
    )


async def get_organization_id(principal: Principal = Depends(get_principal)) -> UUID:
    """Kept deliberately, as a one-line derivative of get_principal.

    The original stub's docstring promised that wiring real auth would be
    "a one-function change here, not a sweep across every route." This
    honors that: ~20 existing route signatures still say
    `Depends(get_organization_id)` and none of them changed.
    """
    return principal.organization_id


# # ASSUMPTION: same in-process limiter pattern as app/main.py's webhook
# limiter (app/policy/rate_limit.py's module docstring already documents the
# multi-instance caveat). Budget is more generous than the public webhook's
# (this is behind the org-header dev-auth stub, not a fully public route),
# but still bounded per CLAUDE.md "rate-limit all public endpoints".
_api_rate_limiter = RateLimiter(max_requests=120, window_seconds=60)


async def rate_limit(request: Request) -> None:
    client_key = request.client.host if request.client else "unknown"
    if not await _api_rate_limiter.allow(client_key):
        raise HTTPException(status_code=429, detail="rate limit exceeded")
