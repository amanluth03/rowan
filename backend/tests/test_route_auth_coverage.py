"""Every /api/v1 route is authenticated, enforced structurally.

This is the test that catches "someone added a route and forgot." It walks
the live router rather than a maintained list, so a new unauthenticated
route fails CI the moment it is added.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from app.api.deps import get_organization_id, get_principal
from app.main import app

# Routes that are deliberately reachable without a Rowan principal, each
# with its own compensating control:
#   /orgs/bootstrap      -- caller has a verified Supabase JWT but no org yet
#                           (that is the point); verified inside the handler.
#   /invitations/accept  -- same, plus a single-use hashed invite token.
# Both are rate-limited. Adding to this set is a security decision and must
# be reviewed as one.
_UNAUTHENTICATED_ALLOWLIST = {
    "/api/v1/orgs/bootstrap",
    "/api/v1/invitations/accept",
}


def _dependency_callables(route: APIRoute) -> set:
    return {d.call for d in route.dependant.dependencies} | {
        sub.call for d in route.dependant.dependencies for sub in d.dependencies
    }


def test_every_api_v1_route_requires_a_principal():
    offenders = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/v1"):
            continue
        if route.path in _UNAUTHENTICATED_ALLOWLIST:
            continue

        deps = _dependency_callables(route)
        param_deps = {
            p.dependant.call
            for p in route.dependant.dependencies
            if p.dependant is not None
        }
        # A route is authenticated if get_principal appears anywhere in its
        # dependency tree -- directly, via get_organization_id, or via
        # require_role's closure.
        flat = repr(deps | param_deps) + repr(route.dependant.dependencies)
        if not (
            get_principal in deps
            or get_organization_id in deps
            or "get_principal" in flat
            or "get_organization_id" in flat
            or "_dependency" in flat
        ):
            offenders.append(f"{list(route.methods)} {route.path}")

    assert offenders == [], f"unauthenticated /api/v1 routes: {offenders}"


@pytest.mark.xfail(
    reason="allowlist names /api/v1/orgs/bootstrap and /api/v1/invitations/accept, "
    "which land in Tasks 8 and 10 respectively -- remove this marker in Task 10",
    strict=True,
)
def test_allowlist_entries_still_exist():
    """A stale allowlist entry silently widens the guard. If a route is
    renamed or removed, this fails so the allowlist gets pruned too."""
    paths = {r.path for r in app.routes if isinstance(r, APIRoute)}
    missing = _UNAUTHENTICATED_ALLOWLIST - paths
    assert missing == set(), f"allowlist names routes that no longer exist: {missing}"
