"""The COMMAND_ROLES table is the authorization contract. These tests pin
its shape, not its current contents -- the completeness test is what makes
adding a command without a role decision impossible to merge."""

from __future__ import annotations

import pytest

from app.models.enums import UserRole
from app.policy.permissions import (
    COMMAND_ROLES,
    Command,
    UnknownCommandError,
    is_permitted,
)


def test_every_command_has_a_role_mapping():
    missing = [c for c in Command if c not in COMMAND_ROLES]
    assert missing == [], f"commands with no COMMAND_ROLES entry: {missing}"


def test_no_command_is_mapped_to_the_empty_set():
    unusable = [c for c, roles in COMMAND_ROLES.items() if not roles]
    assert unusable == [], f"commands nobody can run: {unusable}"


def test_owner_can_do_everything():
    for command in Command:
        assert is_permitted(command, UserRole.owner), command


@pytest.mark.parametrize(
    "command",
    [
        Command.add_vendor,
        Command.set_requirements,
        Command.approve_review,
        Command.reject_review,
        Command.resolve_escalation,
        Command.invite_user,
        Command.revoke_invitation,
        Command.list_invitations,
    ],
)
def test_assistant_is_denied_owner_only_commands(command):
    assert not is_permitted(command, UserRole.assistant)


@pytest.mark.parametrize(
    "command",
    [Command.start_run, Command.pause_run, Command.resume_run, Command.request_revision],
)
def test_assistant_can_run_the_day_to_day_loop(command):
    assert is_permitted(command, UserRole.assistant)


def test_unmapped_command_raises_rather_than_allowing():
    # Default-deny is structural: an unmapped command is a loud failure,
    # never a silent allow.
    class Fake(str):
        pass

    with pytest.raises(UnknownCommandError):
        is_permitted(Fake("not_a_real_command"), UserRole.owner)
