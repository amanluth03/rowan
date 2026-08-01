"""Every route is authenticated (or explicitly, narrowly public), enforced
structurally.

This is the test that catches "someone added a route and forgot." It walks
the live router rather than a maintained list, so a new unauthenticated
route fails CI the moment it is added.

F1 (security review of Tasks 8-10, BLOCK): the first version of this fix
selected routes by `path.startswith("/api/v1")` after flattening. That is a
fail-OPEN filter -- a route mounted via `include_router(r, prefix="/api/v1")`
(prefix applied at inclusion time, not baked into the sub-router's own
construction) or nested two-plus routers deep resolves its RAW,
un-prefixed path (`/x`, `/sneaky`, ...) unless that prefix is explicitly
accumulated during the walk, and would have been silently skipped by the
`startswith` check -- never reaching the auth check at all. Fixed two ways:
  1. `_flatten_api_routes` now accumulates each ancestor `_IncludedRouter`'s
     `include_context.prefix` on the way down, so the reported path is the
     TRUE mount path regardless of where in the router tree the prefix was
     applied (see `test_flatten_resolves_prefixed_include_router` and
     `test_flatten_resolves_depth_two_nested_router` below).
  2. The filter is inverted: every flattened route is audited UNLESS it
     matches an explicit, narrow public surface (`_is_public`) -- never
     selected-in by a path prefix that a new route could simply not match.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, FastAPI
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

# The rest of Rowan's deliberately-public surface, verified in-handler by
# its own compensating control rather than get_principal:
#   /health              -- liveness probe, no data.
#   /webhooks/*           -- provider signature verified inside the handler
#                           (app/webhooks/resend_inbound.py).
#   /internal/*           -- static bearer token verified inside the handler
#                           (app/main.py::_check_internal_token).
# Exact-match / prefix-match, NOT a broad "everything under /api/v1 is
# exempt" shape -- see the F1 note above for why that shape is unsafe.
_PUBLIC_EXACT_PATHS = {"/health"}
_PUBLIC_PATH_PREFIXES = ("/webhooks/", "/internal/")


def _is_public(path: str) -> bool:
    return (
        path in _PUBLIC_EXACT_PATHS
        or path in _UNAUTHENTICATED_ALLOWLIST
        or any(path.startswith(prefix) for prefix in _PUBLIC_PATH_PREFIXES)
    )


@dataclass(frozen=True)
class _ResolvedRoute:
    """A leaf `APIRoute` plus its TRUE mount path, after accumulating every
    ancestor router's include-time prefix (see module docstring, F1)."""

    path: str
    methods: frozenset[str]
    dependant: Any
    route: APIRoute


def _flatten_api_routes(routes, prefix: str = "") -> list[_ResolvedRoute]:
    """Recursively resolve `app.routes` down to `_ResolvedRoute`s, correctly
    prefixed no matter how deep or where in the router tree that prefix was
    applied.

    # ASSUMPTION: the installed FastAPI (0.139) defers each
    # `app.include_router(...)` into an internal `_IncludedRouter` wrapper
    # for lazy "effective route" resolution, rather than flattening
    # sub-router routes into `app.routes` directly as older FastAPI did.
    # A naive `isinstance(route, APIRoute)` walk over `app.routes` therefore
    # silently finds zero routes for every router mounted via
    # `include_router` -- this made the tests below vacuously true/false
    # regardless of what routes exist, independent of Task 10.
    #
    # Each `_IncludedRouter`'s `include_context.prefix` carries whatever
    # prefix was passed to `include_router(..., prefix=...)` at THAT
    # inclusion call -- separate from, and not baked into, any prefix the
    # sub-router itself was constructed with (`APIRouter(prefix=...)`,
    # which IS already baked into that router's own routes' `.path`).
    # Accumulating `include_context.prefix` down each recursion level (empty
    # string when a level has none) and prepending it to the leaf route's
    # own `.path` reconstructs the real dispatched path for every shape:
    # prefix-at-construction (this app's actual routers), prefix-at-include,
    # and N-level nesting of either. Verified empirically against throwaway
    # `FastAPI()` apps for both shapes the security review flagged -- see
    # `test_flatten_resolves_prefixed_include_router` and
    # `test_flatten_resolves_depth_two_nested_router`.
    """
    flat: list[_ResolvedRoute] = []
    for route in routes:
        if isinstance(route, APIRoute):
            flat.append(
                _ResolvedRoute(
                    path=prefix + route.path,
                    methods=frozenset(route.methods or set()),
                    dependant=route.dependant,
                    route=route,
                )
            )
            continue
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            include_context = getattr(route, "include_context", None)
            include_prefix = getattr(include_context, "prefix", "") or ""
            flat.extend(_flatten_api_routes(original_router.routes, prefix + include_prefix))
    return flat


def _dependency_callables(dependant) -> set:
    return {d.call for d in dependant.dependencies} | {
        sub.call for d in dependant.dependencies for sub in d.dependencies
    }


def _find_unauthenticated_routes(target_app) -> list[str]:
    """The actual audit, factored out so both the real app and the F1
    regression tests below (throwaway apps) run the identical check."""
    offenders = []
    for resolved in _flatten_api_routes(target_app.routes):
        if _is_public(resolved.path):
            continue

        deps = _dependency_callables(resolved.dependant)
        # A route is authenticated if get_principal appears anywhere in its
        # dependency tree -- directly, via get_organization_id, or via
        # require_role's closure. (`Dependant.dependencies` is itself a list
        # of `Dependant`, not a wrapper with a further `.dependant` --
        # there's no third level of indirection to unwrap here.)
        flat = repr(deps) + repr(resolved.dependant.dependencies)
        if not (
            get_principal in deps
            or get_organization_id in deps
            or "get_principal" in flat
            or "get_organization_id" in flat
            or "_dependency" in flat
        ):
            offenders.append(f"{sorted(resolved.methods)} {resolved.path}")
    return offenders


def test_every_api_v1_route_requires_a_principal():
    offenders = _find_unauthenticated_routes(app)
    assert offenders == [], f"unauthenticated routes: {offenders}"


def test_allowlist_entries_still_exist():
    """A stale allowlist entry silently widens the guard. If a route is
    renamed or removed, this fails so the allowlist gets pruned too."""
    paths = {r.path for r in _flatten_api_routes(app.routes)}
    missing = _UNAUTHENTICATED_ALLOWLIST - paths
    assert missing == set(), f"allowlist names routes that no longer exist: {missing}"


# ---------------------------------------------------------------------------
# F1 regressions: the two shapes the security review proved evaded the
# original path.startswith("/api/v1") filter. Built against throwaway
# FastAPI() apps -- never added to the real `app`.
# ---------------------------------------------------------------------------


def test_flatten_resolves_prefixed_include_router():
    """`include_router(router, prefix=...)` -- prefix applied at inclusion
    time, not baked into the sub-router's own construction -- must resolve
    to the true mounted path, not the router's raw, un-prefixed one."""
    throwaway = FastAPI()
    sub = APIRouter()

    @sub.get("/x")
    def _endpoint():  # pragma: no cover - never called, route shape only
        return {"ok": True}

    throwaway.include_router(sub, prefix="/api/v1")

    paths = {r.path for r in _flatten_api_routes(throwaway.routes)}
    assert "/api/v1/x" in paths
    assert "/x" not in paths


def test_flatten_resolves_depth_two_nested_router():
    """A router nested two levels deep (`mid.include_router(inner)`, then
    `app.include_router(mid, prefix=...)`) must still resolve to its true
    mount path, not the leaf router's raw path."""
    throwaway = FastAPI()
    inner = APIRouter()

    @inner.get("/sneaky")
    def _endpoint():  # pragma: no cover - never called, route shape only
        return {"ok": True}

    mid = APIRouter()
    mid.include_router(inner)
    throwaway.include_router(mid, prefix="/api/v1")

    paths = {r.path for r in _flatten_api_routes(throwaway.routes)}
    assert "/api/v1/sneaky" in paths
    assert "/sneaky" not in paths


def test_guard_catches_unauthenticated_route_mounted_via_prefixed_include():
    """The exact failure mode security review proved live: an unauthenticated
    route reachable only through `include_router(..., prefix=...)` must be
    flagged as an offender -- not silently skipped because its raw,
    pre-mount path didn't happen to start with "/api/v1". This is the
    required verification evidence for F1, not just a shape check."""
    throwaway = FastAPI()
    sub = APIRouter()

    @sub.get("/x")
    def _leaky():  # no Depends(get_principal) anywhere in this route
        return {"leaked": True}

    throwaway.include_router(sub, prefix="/api/v1")

    offenders = _find_unauthenticated_routes(throwaway)
    assert offenders == ["['GET'] /api/v1/x"]
