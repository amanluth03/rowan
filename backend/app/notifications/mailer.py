"""Layer 5-adjacent transactional mail: account lifecycle messages that
belong to no run.

Explicitly NOT app/tools/send_email.py. That module is an Orchestration
tool bound to a run: run-scoped idempotency keys, per-run outreach budgets,
agent_events rows tied to a run_id (ADR 0004). An invitation has no run, so
sending it through that tool would require a null run_id and would erode
invariants the guardrail story depends on. This is the smaller, separate
path.

What it keeps from the tool layer: the global kill switch, an idempotency
key, and the send-only Resend credential.

# ASSUMPTION: auth mail and agent outreach share one send-only Resend key.
# A second scoped key would be cleaner under CLAUDE.md's least-privilege
# posture; flagged for follow-up, not blocking.
"""

from __future__ import annotations

from app.config import settings
from app.tools import resend_client


class MailerError(Exception):
    """Raised when a transactional send is refused or fails."""


async def _resend_send(
    *, to: str, subject: str, html: str, text: str | None = None, idempotency_key: str | None = None
):
    """Adapts this module's (to/html/text/idempotency_key) vocabulary to the
    real `app.tools.resend_client.send`, which this module must not modify
    (it's shared with the agent's outreach path -- app/tools/send_email.py).

    # ASSUMPTION: `resend_client.send()`'s actual signature is
    # `(*, to_email, from_email, subject, html_body, reply_to=None) ->
    # SendResult(ok, provider_message_id, error)` -- it does not raise on
    # failure, it returns ok=False, and it has no `text` or
    # `idempotency_key` parameter at all. Adaptations made here:
    #   - name translation: to -> to_email, html -> html_body, plus
    #     from_email supplied from settings (the tool-layer caller,
    #     send_email.py, gets from_email from its own input; this module
    #     has no such input, so it uses settings.resend_from_email
    #     directly, same value send_email.py is configured with).
    #   - `text` (the plain-text alternative body) is accepted here for
    #     interface parity with render_invite_email's three-tuple output,
    #     but is NOT currently transmitted to Resend -- resend_client's
    #     payload only ever sends `html`. Only the HTML body reaches
    #     recipients. Flagged for follow-up (Resend's API does accept a
    #     `text` field; wiring it up means touching the shared client,
    #     out of scope here), not blocking for v1's single transactional
    #     email.
    #   - `idempotency_key` is likewise accepted but not forwarded --
    #     Resend supports a provider-side idempotency header (see
    #     app/tools/send_email.py's docstring, which notes the same gap
    #     for vendor outreach) but resend_client.py does not wire one up
    #     yet, and this module must not modify that shared client. This
    #     module's own idempotency key is real (Task 10 must use it to
    #     avoid re-inviting on retry) but the dedup guarantee currently
    #     comes from the caller checking invite state before calling
    #     send_transactional, not from Resend-side deduplication.
    #   - `SendResult.ok is False` is translated into a raised exception
    #     here (rather than send_transactional inspecting a return value),
    #     so send_transactional's single try/except around the send call
    #     covers both "resend_client raised" and "resend_client returned
    #     a failure" uniformly.
    """
    result = await resend_client.send(
        to_email=to,
        from_email=settings.resend_from_email,
        subject=subject,
        html_body=html,
    )
    if not result.ok:
        raise RuntimeError(result.error or "resend send failed")
    return result


async def send_transactional(
    *, to: str, subject: str, html: str, text: str, idempotency_key: str
) -> None:
    # Highest-priority guardrail, checked before every outbound action
    # (CLAUDE.md): the global kill switch halts outbound while leaving
    # reads intact. Auth mail is outbound.
    if settings.rowan_kill_switch:
        raise MailerError("global kill switch is engaged; refusing to send")

    # No "resend_api_key not configured" gate here: resend_client.send()
    # already handles that case itself (local/dev/test simulate a
    # successful send with a deterministic fake id -- see its own
    # ASSUMPTION comment), and app/tools/send_email.py relies on the same
    # behavior rather than gating in the caller. Duplicating the gate here
    # would make this module unusable in the same unconfigured-local
    # environment the rest of the codebase runs tests against.
    try:
        await _resend_send(
            to=to,
            subject=subject,
            html=html,
            text=text,
            idempotency_key=idempotency_key,
        )
    except Exception as e:
        raise MailerError(f"transactional send failed: {e}") from e
