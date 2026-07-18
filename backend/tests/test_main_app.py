"""Tests for app/main.py's public webhook route hardening
(security-reviewer finding, 2026-07-18, blocking): a pre-auth body-size cap
and rate limiting on /webhooks/resend/inbound, the one public endpoint in
this backend. Both must reject BEFORE the expensive work (full body read,
HMAC verification) — a cap or limiter that only kicks in after buffering
the whole body or computing HMAC doesn't actually bound the cost of an
attack.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import httpx
import pytest

pytestmark = pytest.mark.asyncio

SECRET = "whsec_dGVzdF9zZWNyZXRfa2V5X2Zvcl90ZXN0cw=="


def _sign(secret: str, svix_id: str, svix_timestamp: str, body: bytes) -> str:
    signed_content = f"{svix_id}.{svix_timestamp}.{body.decode()}"
    key = base64.b64decode(secret.split("_", 1)[1] + "==")
    sig = hmac.new(key, signed_content.encode(), hashlib.sha256).digest()
    return "v1," + base64.b64encode(sig).decode()


@pytest.fixture
async def client(monkeypatch):
    # NOTE: does NOT call init_pools()/close_pools() itself — the
    # session-scoped, autouse `_pools` fixture in conftest.py already owns
    # that lifecycle for the whole test session. Calling close_pools() here
    # would tear down the shared pool out from under every other test file
    # sharing the session event loop (this bit us once already: it turned
    # into 56 unrelated failures across the suite before this comment was
    # added).
    from app import config as config_module
    from app.main import app

    monkeypatch.setattr(config_module.settings, "resend_webhook_secret", SECRET)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


class TestBodySizeCap:
    async def test_oversized_body_rejected_before_signature_check(self, client):
        # Body is huge AND has a deliberately WRONG signature. If the size
        # cap runs first (as required), we get 413, never 401 — proving the
        # cap short-circuits before any HMAC work happens.
        huge_body = json.dumps({"data": {"to": [], "junk": "x" * (25 * 1024 * 1024)}}).encode()
        resp = await client.post(
            "/webhooks/resend/inbound",
            content=huge_body,
            headers={
                "svix-id": "msg_huge",
                "svix-timestamp": "1700000000",
                "svix-signature": "v1,not-even-valid-base64!!!",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 413

    async def test_normal_sized_body_not_rejected_by_cap(self, client):
        payload = {"data": {"to": ["unknown_token@reply.rowan.example.com"], "attachments": []}}
        body = json.dumps(payload).encode()
        svix_id = "msg_normal"
        svix_ts = "1700000000"
        sig = _sign(SECRET, svix_id, svix_ts, body)
        resp = await client.post(
            "/webhooks/resend/inbound",
            content=body,
            headers={
                "svix-id": svix_id,
                "svix-timestamp": svix_ts,
                "svix-signature": sig,
                "content-type": "application/json",
            },
        )
        assert resp.status_code != 413
        assert resp.status_code == 200


class TestRateLimiting:
    async def test_repeated_requests_eventually_rate_limited(self, client):
        payload = {"data": {"to": ["unknown_token@reply.rowan.example.com"], "attachments": []}}
        body = json.dumps(payload).encode()

        statuses = []
        for i in range(80):
            svix_id = f"msg_rl_{i}"
            svix_ts = "1700000000"
            sig = _sign(SECRET, svix_id, svix_ts, body)
            resp = await client.post(
                "/webhooks/resend/inbound",
                content=body,
                headers={
                    "svix-id": svix_id,
                    "svix-timestamp": svix_ts,
                    "svix-signature": sig,
                    "content-type": "application/json",
                },
            )
            statuses.append(resp.status_code)

        assert 429 in statuses, f"expected a 429 among {set(statuses)} after {len(statuses)} rapid requests"
