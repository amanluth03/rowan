"""Inbound-email webhook handler (Resend, Svix-signed per Resend's webhook
implementation). Verifies the provider signature, resolves
`reply_token -> run -> organization_id` (the one legitimate pre-GUC lookup,
see migrations/0008_rls.sql's gap note), and is idempotent against provider
replay via the shared `tool_invocations` ledger — a redelivered webhook
(same `svix-id`) must never re-store the attachment or re-drive the state
machine.

# ASSUMPTION: signature verification implements the documented Svix
scheme (HMAC-SHA256 over "{svix_id}.{svix_timestamp}.{body}", secret
prefixed `whsec_` + base64), which is what Resend uses for webhook signing.
Not tested against a live Resend account in this build — flagged for
security-reviewer to double-check against Resend's current docs before
this goes live, and for a timestamp-tolerance check (replay window) to be
added, which this v1 implementation does not yet enforce.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from typing import Any
from uuid import UUID

from app.config import settings
from app.db import org_scoped_tx, system_conn
from app.orchestration.runner import handle_inbound_document
from app.tools import idempotency

REPLY_TOKEN_PATTERN = re.compile(r"^([^@]+)@reply\.rowan\.[a-zA-Z0-9.\-]+$")


class WebhookVerificationError(Exception):
    pass


def verify_signature(
    *, secret: str, svix_id: str, svix_timestamp: str, body: bytes, svix_signature: str
) -> bool:
    if not secret:
        raise WebhookVerificationError("no webhook secret configured")

    key_material = secret.split("_", 1)[1] if secret.startswith("whsec_") else secret
    try:
        key = base64.b64decode(key_material + "==")  # tolerate missing padding
    except Exception as e:
        raise WebhookVerificationError(f"malformed secret: {e}") from e

    signed_content = f"{svix_id}.{svix_timestamp}.{body.decode('utf-8')}".encode("utf-8")
    expected = hmac.new(key, signed_content, hashlib.sha256).digest()
    expected_b64 = base64.b64encode(expected).decode()

    # svix-signature may carry multiple space-separated "v1,<sig>" values
    # (secret rotation); any match is valid.
    provided_sigs = svix_signature.split()
    for sig in provided_sigs:
        _, _, value = sig.partition(",")
        if value and hmac.compare_digest(value, expected_b64):
            return True

    raise WebhookVerificationError("signature mismatch")


def _extract_reply_token(to_addresses: list[str]) -> str | None:
    for addr in to_addresses:
        m = REPLY_TOKEN_PATTERN.match(addr.strip())
        if m:
            return m.group(1)
    return None


async def _resolve_run(reply_token: str) -> tuple[UUID, UUID] | None:
    """reply_token -> (run_id, organization_id), via the narrow
    rowan_system column-restricted grant (migrations/0008_rls.sql)."""
    async with system_conn() as conn:
        row = await conn.fetchrow(
            "select id, organization_id, reply_token_expires_at, status from runs where reply_token = $1",
            reply_token,
        )
    if row is None:
        return None
    if row["status"] != "active":
        return None
    import datetime as _dt

    if row["reply_token_expires_at"] is not None and row["reply_token_expires_at"] < _dt.datetime.now(
        _dt.timezone.utc
    ):
        return None
    return row["id"], row["organization_id"]


async def handle_inbound_webhook(
    *, body: bytes, svix_id: str, svix_timestamp: str, svix_signature: str
) -> dict[str, Any]:
    verify_signature(
        secret=settings.resend_webhook_secret,
        svix_id=svix_id,
        svix_timestamp=svix_timestamp,
        body=body,
        svix_signature=svix_signature,
    )

    import json

    payload = json.loads(body)
    data = payload.get("data", {})
    to_addresses = data.get("to", [])
    reply_token = _extract_reply_token(to_addresses)
    if reply_token is None:
        return {"status": "ignored", "reason": "no_reply_token_in_recipients"}

    resolved = await _resolve_run(reply_token)
    if resolved is None:
        return {"status": "ignored", "reason": "unknown_or_expired_reply_token"}
    run_id, organization_id = resolved

    # Idempotency against provider replay, now that we know the org (GUC
    # can be set). svix_id is Resend/Svix's own delivery id — stable across
    # redeliveries of the SAME event.
    request_hash = hashlib.sha256(body).hexdigest()
    async with org_scoped_tx(organization_id) as conn:
        outcome = await idempotency.reserve(
            conn,
            organization_id=organization_id,
            run_id=run_id,
            tool_name="webhook_resend_inbound",
            idempotency_key=svix_id,
            request_hash=request_hash,
        )
    if not outcome.proceed:
        if outcome.replay:
            return {"status": "replayed"}
        return {"status": "ignored", "reason": "duplicate_in_progress"}

    attachments = data.get("attachments", [])
    if not attachments:
        async with org_scoped_tx(organization_id) as conn:
            await idempotency.complete(
                conn, outcome.invocation_id, status="failed", error={"reason": "no_attachments"}
            )
        return {"status": "ignored", "reason": "no_attachments"}

    # ADR 0002 guard is "≥1 attachment passing guardrails" — process the
    # first attachment; multiple attachments per inbound email are treated
    # as a v2 concern (out of scope: CLAUDE.md non-goals list bulk import,
    # and multi-doc-per-run isn't part of the locked state machine shape).
    first = attachments[0]
    file_bytes = base64.b64decode(first["content_base64"])

    result = await handle_inbound_document(
        organization_id,
        run_id,
        filename=first.get("filename", "attachment"),
        data=file_bytes,
        content_type=first.get("content_type", "application/octet-stream"),
    )

    async with org_scoped_tx(organization_id) as conn:
        await idempotency.complete(
            conn,
            outcome.invocation_id,
            status="succeeded",
            response={"advanced": result is not None},
        )

    return {"status": "processed", "advanced": result is not None}
