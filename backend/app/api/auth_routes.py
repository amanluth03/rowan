"""Interface-layer auth routes: organization bootstrap and invitations.

These are the only /api/v1 routes NOT behind get_principal -- by necessity,
since their callers have a verified Supabase identity but no Rowan
organization yet. Each verifies the JWT itself, in-handler, and is
rate-limited. They are named explicitly in
tests/test_route_auth_coverage.py's allowlist so the exception is visible
rather than implicit.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException

from app.api.deps import rate_limit
from app.api.schemas import BootstrapOrgRequest, BootstrapOrgResponse
from app.policy.auth import Claims, InvalidTokenError, verify_supabase_jwt
from app.orchestration import runner

router = APIRouter(prefix="/api/v1", tags=["auth"], dependencies=[Depends(rate_limit)])


async def _verified_claims(authorization: str | None = Header(default=None)) -> Claims:
    """Like get_principal, but stops at "this is a real Supabase user" --
    it does NOT require an existing Rowan org, which is the whole point of
    the routes in this module."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        return await verify_supabase_jwt(authorization[7:].strip())
    except InvalidTokenError as e:
        raise HTTPException(status_code=401, detail="Not authenticated") from e


@router.post("/orgs/bootstrap", response_model=BootstrapOrgResponse, status_code=201)
async def bootstrap_org(
    body: BootstrapOrgRequest, claims: Claims = Depends(_verified_claims)
) -> BootstrapOrgResponse:
    if not claims.email:
        raise HTTPException(status_code=422, detail="Your account has no email address.")
    try:
        organization_id, user_id = await runner.bootstrap_organization(
            auth_user_id=claims.sub,
            email=claims.email,
            full_name=body.full_name,
            org_name=body.organization_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return BootstrapOrgResponse(organization_id=organization_id, user_id=user_id)
