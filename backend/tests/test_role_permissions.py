"""ACCEPTANCE CRITERION 3: owner and assistant, enforced at the HTTP edge.

Driven by COMMAND_ROLES itself rather than a hand-written list, so a command
added without a role decision cannot pass silently -- it fails
test_permissions.py's completeness check, and any route wired to it shows up
here.
"""

from __future__ import annotations

import httpx
import pytest

from app.models.enums import UserRole
from app.policy.permissions import COMMAND_ROLES, Command

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def client():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def _route_for(command: Command, ctx: dict) -> tuple[str, str, dict]:
    """(method, path, json_body) exercising each command over HTTP."""
    vendor_id, run_id, escalation_id = ctx["vendor_id"], ctx["run_id"], ctx["escalation_id"]
    return {
        Command.add_vendor: ("POST", "/api/v1/vendors", {
            "name": "X", "primaryEmail": "x@example.com", "vendorRole": "plumber"}),
        Command.set_requirements: ("POST", f"/api/v1/vendors/{vendor_id}/requirements", {"lines": []}),
        Command.start_run: ("POST", f"/api/v1/runs/{run_id}/start", {}),
        Command.pause_run: ("POST", f"/api/v1/runs/{run_id}/pause", {}),
        Command.resume_run: ("POST", f"/api/v1/runs/{run_id}/resume", {}),
        Command.approve_review: ("POST", f"/api/v1/reviews/{escalation_id}/approve", {}),
        Command.reject_review: ("POST", f"/api/v1/reviews/{escalation_id}/reject", {"reason": "no"}),
        Command.request_revision: ("POST", f"/api/v1/reviews/{escalation_id}/request-revision", {"reason": "fix"}),
        Command.resolve_escalation: ("POST", f"/api/v1/escalations/{escalation_id}/resolve", {}),
        Command.invite_user: ("POST", "/api/v1/invitations", {"email": "new@example.com"}),
        Command.list_invitations: ("GET", "/api/v1/invitations", None),
        Command.revoke_invitation: ("POST", f"/api/v1/invitations/{ctx['invitation_id']}/revoke", {}),
    }[command]


@pytest.fixture
async def ctx(org_with_users, make_run, admin_conn):
    from app.ids import uuid7

    run_id = await make_run()
    escalation_id = uuid7()
    invitation_id = uuid7()
    # ASSUMPTION: `kind='needs_human_review'` so this one row backs three of
    # the four review/escalation route entries (approve/reject/request-
    # revision all require that kind per runner._load_open_escalation_for_
    # command). resolve_escalation (kind='escalated_to_pm') will therefore
    # get a 409 "no open escalation" for the owner rather than a 200 -- that
    # is fine for what this file asserts (never 403 for the owner; assistant
    # denied iff COMMAND_ROLES says so), since require_role's 403 check runs
    # as a router dependency before the handler body ever looks the
    # escalation up. A single fixture row cannot simultaneously satisfy both
    # kinds, and standing up a full needs_human_review -> escalated_to_pm
    # run for one HTTP-shape check is out of scope for this file (that
    # transition already has its own coverage in
    # test_orchestration_filing_and_human_review.py).
    await admin_conn.execute(
        """
        insert into escalations
            (id, organization_id, run_id, vendor_id, kind, reason_code, severity, summary, status)
        values ($1,$2,$3,$4,'needs_human_review','test_reason','warn','test summary','open')
        """,
        escalation_id, org_with_users["org_id"], run_id, org_with_users["vendor_id"],
    )
    await admin_conn.execute(
        "insert into invitations (id, organization_id, email, role, token_hash, expires_at) "
        "values ($1,$2,'pending@example.com','assistant',$3, now() + interval '7 days')",
        invitation_id, org_with_users["org_id"], f"h_{invitation_id}",
    )
    return {
        **org_with_users,
        "run_id": run_id,
        "escalation_id": escalation_id,
        "invitation_id": invitation_id,
    }


@pytest.mark.parametrize("command", list(Command))
async def test_assistant_is_denied_exactly_the_owner_only_commands(
    command, client, jwt_harness, ctx, monkeypatch
):
    async def _noop(**kwargs):
        return None

    monkeypatch.setattr("app.orchestration.runner.send_transactional", _noop)

    method, path, body = _route_for(command, ctx)
    headers = {"Authorization": f"Bearer {jwt_harness.mint(ctx['assistant_auth_id'])}"}
    resp = await (
        client.get(path, headers=headers) if method == "GET"
        else client.post(path, json=body, headers=headers)
    )

    assistant_allowed = UserRole.assistant in COMMAND_ROLES[command]
    if assistant_allowed:
        assert resp.status_code != 403, f"{command} should be allowed for assistant"
    else:
        assert resp.status_code == 403, (
            f"{command} must be owner-only, got {resp.status_code}: {resp.text}"
        )


@pytest.mark.parametrize("command", list(Command))
async def test_owner_is_never_denied_by_role(command, client, jwt_harness, ctx, monkeypatch):
    async def _noop(**kwargs):
        return None

    monkeypatch.setattr("app.orchestration.runner.send_transactional", _noop)

    method, path, body = _route_for(command, ctx)
    headers = {"Authorization": f"Bearer {jwt_harness.mint(ctx['owner_auth_id'])}"}
    resp = await (
        client.get(path, headers=headers) if method == "GET"
        else client.post(path, json=body, headers=headers)
    )
    assert resp.status_code != 403, f"owner denied {command}: {resp.text}"


async def test_every_command_is_covered_by_this_file(ctx):
    """If a command has no HTTP mapping above, the matrix silently stops
    testing it. This makes that impossible."""
    unmapped = []
    for command in Command:
        try:
            method, path, _ = _route_for(command, ctx)
        except KeyError:
            unmapped.append(command)
            continue
        assert method in ("GET", "POST"), f"{command}: bad method {method}"
        assert path.startswith("/api/v1/"), f"{command}: bad path {path}"
        assert "None" not in path, f"{command}: path has an unfilled fixture id: {path}"
    assert unmapped == [], f"commands with no HTTP mapping in _route_for: {unmapped}"


# ---------------------------------------------------------------------------
# The policy itself, pinned as a literal.
#
# Every test above derives its expectation FROM COMMAND_ROLES, so it proves
# the routes agree with the table -- it can never catch the table being
# wrong. Flipping approve_review to _BOTH flips the expectation too, and the
# whole matrix still passes. Verified: it does.
#
# This is the test that objects. It restates the intended policy
# independently, so silently widening a permission fails CI instead of
# quietly shipping. The decision it encodes (CLAUDE.md, ADR 0007): approving
# a COI is the moment Rowan tells Dana "you're covered", and her licence is
# on the line -- that sign-off stays with the owner. The chasing does not.
# ---------------------------------------------------------------------------

_EXPECTED_OWNER_ONLY = {
    "add_vendor",
    "set_requirements",
    "approve_review",
    "reject_review",
    "resolve_escalation",
    "invite_user",
    "revoke_invitation",
    "list_invitations",
}

_EXPECTED_BOTH_ROLES = {
    "start_run",
    "pause_run",
    "resume_run",
    "request_revision",
}


async def test_command_roles_matches_the_intended_policy():
    """Changing COMMAND_ROLES must be a deliberate, reviewed act.

    If you are here because this test failed, do not simply update the sets
    below to match the code. Decide first whether the permission change is
    intended, then change both together.
    """
    actual_owner_only = {
        c.value for c, roles in COMMAND_ROLES.items() if roles == frozenset({UserRole.owner})
    }
    actual_both = {
        c.value
        for c, roles in COMMAND_ROLES.items()
        if roles == frozenset({UserRole.owner, UserRole.assistant})
    }

    assert actual_owner_only == _EXPECTED_OWNER_ONLY, (
        "owner-only command set changed: "
        f"added={sorted(actual_owner_only - _EXPECTED_OWNER_ONLY)} "
        f"removed={sorted(_EXPECTED_OWNER_ONLY - actual_owner_only)}"
    )
    assert actual_both == _EXPECTED_BOTH_ROLES, (
        "both-roles command set changed: "
        f"added={sorted(actual_both - _EXPECTED_BOTH_ROLES)} "
        f"removed={sorted(_EXPECTED_BOTH_ROLES - actual_both)}"
    )
    # No command may sit outside those two buckets (e.g. assistant-only, or
    # an empty set nobody can invoke).
    assert _EXPECTED_OWNER_ONLY | _EXPECTED_BOTH_ROLES == {c.value for c in Command}
