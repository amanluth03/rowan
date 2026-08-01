"""Interface-layer auth routes: organization bootstrap and invitations.

These are the only /api/v1 routes NOT behind get_principal -- by necessity,
since their callers have a verified Supabase identity but no Rowan
organization yet. Each verifies the JWT itself, in-handler, and is
rate-limited. They are named explicitly in
tests/test_route_auth_coverage.py's allowlist so the exception is visible
rather than implicit.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException

from app.api.deps import Principal, get_principal, rate_limit, require_role
from app.api.schemas import (
    AcceptInviteRequest,
    AcceptInviteResponse,
    BootstrapOrgRequest,
    BootstrapOrgResponse,
    InvitationDTO,
    InviteUserRequest,
)
from app.models.enums import UserRole
from app.policy.auth import Claims, InvalidTokenError, verify_supabase_jwt
from app.policy.permissions import Command
from app.orchestration import runner
from app.retrieval import invitation_repo

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


@router.post("/invitations", response_model=InvitationDTO, status_code=201,
             dependencies=[Depends(require_role(Command.invite_user))])
async def create_invitation(
    body: InviteUserRequest, principal: Principal = Depends(get_principal)
) -> InvitationDTO:
    try:
        invitation_id = await runner.invite_user(
            organization_id=principal.organization_id,
            inviter_user_id=principal.user_id,
            inviter_email=principal.email,
            email=str(body.email),
            role=UserRole.assistant,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    pending = await invitation_repo.list_pending(principal.organization_id)
    row = next(i for i in pending if i.id == invitation_id)
    return InvitationDTO(
        id=row.id, email=row.email, role=row.role.value, expires_at=row.expires_at
    )


@router.get("/invitations", response_model=list[InvitationDTO],
            dependencies=[Depends(require_role(Command.list_invitations))])
async def list_invitations(
    principal: Principal = Depends(get_principal),
) -> list[InvitationDTO]:
    rows = await invitation_repo.list_pending(principal.organization_id)
    return [
        InvitationDTO(id=r.id, email=r.email, role=r.role.value, expires_at=r.expires_at)
        for r in rows
    ]


@router.post("/invitations/{invitation_id}/revoke", status_code=204,
             dependencies=[Depends(require_role(Command.revoke_invitation))])
async def revoke_invitation(
    invitation_id: UUID, principal: Principal = Depends(get_principal)
) -> None:
    if not await invitation_repo.revoke(principal.organization_id, invitation_id):
        # 404, not 403: an invitation in ANOTHER org must be indistinguishable
        # from one that does not exist.
        raise HTTPException(status_code=404, detail="Invitation not found")


@router.post("/invitations/accept", response_model=AcceptInviteResponse, status_code=201)
async def accept_invitation(
    body: AcceptInviteRequest, claims: Claims = Depends(_verified_claims)
) -> AcceptInviteResponse:
    if not claims.email:
        raise HTTPException(status_code=422, detail="Your account has no email address.")
    try:
        organization_id, user_id = await runner.accept_invitation(
            raw_token=body.token, auth_user_id=claims.sub, email=claims.email
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return AcceptInviteResponse(organization_id=organization_id, user_id=user_id)
