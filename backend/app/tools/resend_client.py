"""Minimal Resend API client — send-only credential, least privilege
(CLAUDE.md Security section). This is the ONLY module that holds/uses the
Resend API key; nothing else in the codebase talks to Resend directly.

# ASSUMPTION: Resend's HTTP API (`POST https://api.resend.com/emails`) is
called directly via httpx rather than the `resend` SDK package, to avoid an
extra dependency for a single endpoint. Swappable later without touching
callers (they only see `SendResult`).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import settings

RESEND_API_URL = "https://api.resend.com/emails"


@dataclass
class SendResult:
    ok: bool
    provider_message_id: str | None
    error: str | None = None


async def send(
    *, to_email: str, from_email: str, subject: str, html_body: str, reply_to: str | None = None
) -> SendResult:
    if not settings.resend_api_key:
        # # ASSUMPTION: no API key configured (local/dev/test) -> simulate a
        # successful send with a deterministic fake provider id, so the rest
        # of the pipeline (idempotency, state transitions) is exercisable
        # without a real Resend account. Never used in prod (resend_api_key
        # is required there via env/Vercel per CLAUDE.md secrets policy).
        import hashlib

        fake_id = "sim_" + hashlib.sha256(f"{to_email}|{subject}".encode()).hexdigest()[:16]
        return SendResult(ok=True, provider_message_id=fake_id)

    payload = {
        "from": from_email,
        "to": [to_email],
        "subject": subject,
        "html": html_body,
    }
    if reply_to:
        payload["reply_to"] = reply_to

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                RESEND_API_URL,
                json=payload,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            )
        if resp.status_code >= 400:
            return SendResult(ok=False, provider_message_id=None, error=f"resend {resp.status_code}: {resp.text}")
        data = resp.json()
        return SendResult(ok=True, provider_message_id=data.get("id"))
    except httpx.HTTPError as e:
        return SendResult(ok=False, provider_message_id=None, error=str(e))
