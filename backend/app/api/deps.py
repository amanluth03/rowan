"""Interface-layer (layer 1) shared dependencies: org-scoping auth stub +
rate limiting. Every route in app/api/ depends on `get_organization_id` for
its `organization_id` — never a client-supplied body/query field — so wiring
real Supabase auth later is a one-function change here, not a sweep across
every route.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Header, HTTPException, Request

from app.policy.rate_limit import RateLimiter

# # ASSUMPTION (flagged prominently in backend/README.md's "Known gaps"):
# real Supabase auth (verify a JWT, resolve `users.auth_user_id ->
# organization_id`) is NOT wired in this pass — that's explicitly out of
# scope for this build (see the task brief). This header is a CLEAR,
# EXPLICITLY-NAMED dev-mode stub standing in for that resolution, not a
# silent default: every command/read-model route derives `organization_id`
# ONLY from this dependency, and the dependency REQUIRES the header (no
# fallback to a fixed demo org) — a request with no header fails closed
# (401), it never silently resolves to "whichever org happens to be first".
# This is deliberately the same shape frontend's `actions.ts` docstring
# flagged as a trap to avoid: never let a client-supplied value (here, an
# unauthenticated header) be silently treated as ground truth without this
# being obvious and load-bearing for reviewers. When real auth lands, only
# this function's body changes (header lookup -> verified-JWT claim lookup);
# no call site changes, because every route already goes through this one
# seam.
ORG_HEADER_NAME = "X-Rowan-Org-Id"


async def get_organization_id(
    x_rowan_org_id: str | None = Header(default=None, alias=ORG_HEADER_NAME),
) -> UUID:
    if not x_rowan_org_id:
        raise HTTPException(
            status_code=401,
            detail=(
                f"{ORG_HEADER_NAME} header required (dev-mode auth stub pending real "
                f"Supabase auth — see backend/README.md's Known gaps section)"
            ),
        )
    try:
        return UUID(x_rowan_org_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{ORG_HEADER_NAME} must be a UUID") from e


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
