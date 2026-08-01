"""Rowan-branded transactional email templates.

Tone follows CLAUDE.md's brand section: calm, audit-grade, "competent
operations person" -- not marketing copy and not an alarm.
"""

from __future__ import annotations

from html import escape

# ASSUMPTION: plain inline-styled HTML rather than a templating engine --
# there is exactly one transactional email in v1. Revisit if a third arrives.


def render_invite_email(
    org_name: str, inviter_email: str, accept_url: str
) -> tuple[str, str, str]:
    safe_org = escape(org_name)
    safe_inviter = escape(inviter_email)
    safe_url = escape(accept_url, quote=True)

    subject = f"You've been invited to {org_name} on Rowan"

    html = f"""\
<div style="font-family:system-ui,-apple-system,sans-serif;max-width:520px;color:#1a1a1a">
  <p>Hi,</p>
  <p>{safe_inviter} has invited you to join <strong>{safe_org}</strong> on Rowan,
     where they track vendor insurance compliance.</p>
  <p>You'll be added as an <strong>assistant</strong>: you can see every vendor,
     run, and document, and keep renewals moving. Changing coverage requirements
     and approving certificates stay with the account owner.</p>
  <p style="margin:28px 0">
    <a href="{safe_url}"
       style="background:#1a1a1a;color:#fff;padding:10px 18px;border-radius:6px;
              text-decoration:none;display:inline-block">Accept the invitation</a>
  </p>
  <p style="color:#666;font-size:13px">This link works once and expires in 7 days.
     If you weren't expecting it, you can ignore this email.</p>
  <p style="color:#666;font-size:13px">— Rowan</p>
</div>"""

    text = f"""\
Hi,

{inviter_email} has invited you to join {org_name} on Rowan, where they track
vendor insurance compliance.

You'll be added as an assistant: you can see every vendor, run, and document,
and keep renewals moving. Changing coverage requirements and approving
certificates stay with the account owner.

Accept the invitation:
{accept_url}

This link works once and expires in 7 days. If you weren't expecting it, you
can ignore this email.

- Rowan
"""
    return subject, html, text
