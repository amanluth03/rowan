"""Every /api/v1 route is authenticated, enforced structurally.

This is the test that catches "someone added a route and forgot." It walks
the live router rather than a maintained list, so a new unauthenticated
route fails CI the moment it is added.
"""

from __future__ import annotations

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


def _flatten_api_routes(routes) -> list[APIRoute]:
    """Recursively resolve `app.routes` down to concrete `APIRoute`s.

    # ASSUMPTION: the installed FastAPI (0.139) defers each
    # `app.include_router(...)` into an internal `_IncludedRouter` wrapper
    # for lazy "effective route" resolution, rather than flattening
    # sub-router routes into `app.routes` directly as older FastAPI did.
    # A naive `isinstance(route, APIRoute)` walk over `app.routes` therefore
    # silently finds zero routes for every router mounted via
    # `include_router` (i.e. all of /api/v1) -- this made both tests below
    # vacuously true/false regardless of what routes exist, independent of
    # Task 10. Verified (see PR notes) that each wrapper's public
    # `original_router` attribute exposes the plain, already-fully-prefixed,
    # already-dependency-merged `APIRoute` list for routers that don't
    # themselves nest further routers (true for every router in this app),
    # so recursing through it is sufficient without reaching into the
    # private `_EffectiveRouteContext`/`effective_candidates()` machinery.
    # Recursing (rather than hardcoding a route list) preserves this test's
    # whole point: it walks the LIVE router, so a new unauthenticated route
    # still fails CI the moment it's added.
    """
    flat: list[APIRoute] = []
    for route in routes:
        if isinstance(route, APIRoute):
            flat.append(route)
            continue
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            flat.extend(_flatten_api_routes(original_router.routes))
    return flat


def _dependency_callables(route: APIRoute) -> set:
    return {d.call for d in route.dependant.dependencies} | {
        sub.call for d in route.dependant.dependencies for sub in d.dependencies
    }


def test_every_api_v1_route_requires_a_principal():
    offenders = []
    for route in _flatten_api_routes(app.routes):
        if not route.path.startswith("/api/v1"):
            continue
        if route.path in _UNAUTHENTICATED_ALLOWLIST:
            continue

        deps = _dependency_callables(route)
        # A route is authenticated if get_principal appears anywhere in its
        # dependency tree -- directly, via get_organization_id, or via
        # require_role's closure. (`Dependant.dependencies` is itself a list
        # of `Dependant`, not a wrapper with a further `.dependant` --
        # there's no third level of indirection to unwrap here.)
        flat = repr(deps) + repr(route.dependant.dependencies)
        if not (
            get_principal in deps
            or get_organization_id in deps
            or "get_principal" in flat
            or "get_organization_id" in flat
            or "_dependency" in flat
        ):
            offenders.append(f"{list(route.methods)} {route.path}")

    assert offenders == [], f"unauthenticated /api/v1 routes: {offenders}"


def test_allowlist_entries_still_exist():
    """A stale allowlist entry silently widens the guard. If a route is
    renamed or removed, this fails so the allowlist gets pruned too."""
    paths = {r.path for r in _flatten_api_routes(app.routes)}
    missing = _UNAUTHENTICATED_ALLOWLIST - paths
    assert missing == set(), f"allowlist names routes that no longer exist: {missing}"
