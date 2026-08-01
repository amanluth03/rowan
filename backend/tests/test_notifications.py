"""The transactional mailer is deliberately NOT app/tools/send_email.py.

send_email is an Orchestration-layer tool with run-scoped idempotency keys
and per-run budgets (ADR 0004). An invite has no run, so routing it through
that tool would mean passing a null run_id and quietly weakening the
invariants the entire guardrail story rests on. This module is the separate,
smaller path: no run, no budget, its own idempotency key.
"""

from __future__ import annotations

import pytest

from app.notifications.mailer import MailerError, send_transactional
from app.notifications.templates import render_invite_email

pytestmark = pytest.mark.asyncio


def test_invite_email_is_rowan_branded():
    subject, html, text = render_invite_email(
        org_name="Dana PM LLC",
        inviter_email="dana@example.com",
        accept_url="https://app.example.com/accept-invite/tok123",
    )
    # CLAUDE.md Naming: every user-facing string says Rowan.
    assert "Rowan" in subject
    assert "Rowan" in html and "Rowan" in text
    assert "Dana PM LLC" in html
    assert "https://app.example.com/accept-invite/tok123" in html
    assert "https://app.example.com/accept-invite/tok123" in text


def test_invite_email_escapes_org_name():
    # org_name is user-supplied at signup -- it must not be able to inject
    # markup into an email we send on the org's behalf.
    _, html, _ = render_invite_email(
        org_name='<script>alert(1)</script>',
        inviter_email="dana@example.com",
        accept_url="https://app.example.com/a/b",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


async def test_send_transactional_calls_resend(monkeypatch):
    sent = {}

    async def _fake_send(**kwargs):
        sent.update(kwargs)
        return {"id": "resend-msg-1"}

    monkeypatch.setattr("app.notifications.mailer._resend_send", _fake_send)
    await send_transactional(
        to="invitee@example.com", subject="s", html="<p>h</p>", text="t",
        idempotency_key="invite:abc",
    )
    assert sent["to"] == "invitee@example.com"


async def test_send_transactional_respects_kill_switch(monkeypatch):
    """The global kill switch halts ALL outbound actions (CLAUDE.md).
    Auth mail is outbound, so it is covered too."""
    from app.config import settings

    monkeypatch.setattr(settings, "rowan_kill_switch", True)
    with pytest.raises(MailerError, match="kill switch"):
        await send_transactional(
            to="invitee@example.com", subject="s", html="<p>h</p>", text="t",
            idempotency_key="invite:abc",
        )
