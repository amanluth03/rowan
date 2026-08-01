"""Layer 5 (Policy): who may invoke which Interface-layer command.

Deliberately DATA (a dict), not scattered `if role == ...` checks -- the
same shape and rationale as this module's sibling app/policy/actions.py,
which holds ACTION_ALLOWLIST for the state machine. One table you can read
top-to-bottom and audit in a review.

DEFAULT-DENY: is_permitted() raises UnknownCommandError for a command with
no entry. Adding a route without making a role decision therefore fails
loudly (and fails tests/test_permissions.py), rather than quietly
defaulting to "everyone".

The split (CLAUDE.md, docs/adr/0007):
  - Owner-only: anything that changes what Rowan is contractually asserting
    -- coverage requirements, the vendor roster, approving/rejecting a COI,
    resolving an escalation, and team membership. Approving a COI is the
    moment Rowan tells Dana "you're covered"; her license is on the line, so
    the sign-off stays with her.
  - Both roles: the day-to-day chasing loop -- start/pause/resume a run,
    ask a vendor for a revision -- plus every read.

Reads are not modeled here: both roles may read everything in their own
org, and cross-org reads are already impossible via RLS.
"""

from __future__ import annotations

from enum import Enum

from app.models.enums import UserRole


class UnknownCommandError(Exception):
    """Raised when a command has no COMMAND_ROLES entry."""


class Command(str, Enum):
    # Vendor + requirements configuration
    add_vendor = "add_vendor"
    set_requirements = "set_requirements"

    # Run operation
    start_run = "start_run"
    pause_run = "pause_run"
    resume_run = "resume_run"

    # Human review
    approve_review = "approve_review"
    reject_review = "reject_review"
    request_revision = "request_revision"
    resolve_escalation = "resolve_escalation"

    # Team management
    invite_user = "invite_user"
    revoke_invitation = "revoke_invitation"
    list_invitations = "list_invitations"


_OWNER_ONLY = frozenset({UserRole.owner})
_BOTH = frozenset({UserRole.owner, UserRole.assistant})

COMMAND_ROLES: dict[Command, frozenset[UserRole]] = {
    Command.add_vendor: _OWNER_ONLY,
    Command.set_requirements: _OWNER_ONLY,
    Command.start_run: _BOTH,
    Command.pause_run: _BOTH,
    Command.resume_run: _BOTH,
    Command.approve_review: _OWNER_ONLY,
    Command.reject_review: _OWNER_ONLY,
    Command.request_revision: _BOTH,
    Command.resolve_escalation: _OWNER_ONLY,
    Command.invite_user: _OWNER_ONLY,
    Command.revoke_invitation: _OWNER_ONLY,
    Command.list_invitations: _OWNER_ONLY,
}


def is_permitted(command: Command, role: UserRole) -> bool:
    try:
        allowed = COMMAND_ROLES[command]
    except KeyError as e:
        raise UnknownCommandError(f"no COMMAND_ROLES entry for {command!r}") from e
    return role in allowed
