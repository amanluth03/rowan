"""FastAPI app factory. Boots the two DB pools (rowan_app, rowan_system) on
startup and exposes the interface-layer (layer 1) surface backend-engineer
owns directly: health check, the inbound-email webhook, and an internal
scheduler-trigger route. Vendor/run/review CRUD routes are frontend-
engineer's territory (Interface -> Orchestration commands per ADR 0003) and
are not built here — this file only wires what backend-engineer's own scope
requires to be independently runnable/testable.
"""

from __future__ import annotations

import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request

from app.api.commands import router as api_commands_router
from app.api.reads import router as api_reads_router
from app.config import settings
from app.db import close_pools, init_pools
from app.orchestration.scheduler import scheduler_tick
from app.policy.rate_limit import RateLimiter
from app.webhooks.resend_inbound import WebhookVerificationError, handle_inbound_webhook


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pools()
    yield
    await close_pools()


app = FastAPI(title="Rowan Vendor COI Renewal Agent — backend", lifespan=lifespan)

# Interface-layer (layer 1) HTTP surface: the 9 ADR 0003 commands + the 4
# read-model DTOs. See app/api/commands.py and app/api/reads.py — both are
# rate-limited (app/api/deps.py) and org-scoped via the X-Rowan-Org-Id
# dev-auth stub (see backend/README.md's Known gaps section).
app.include_router(api_commands_router)
app.include_router(api_reads_router)

# security-reviewer finding (2026-07-18, blocking): the public webhook must
# reject oversized bodies and excessive request rates BEFORE doing any
# expensive work (full body buffering, HMAC verification) — a cap/limiter
# that only kicks in afterward doesn't actually bound attack cost.
#
# # ASSUMPTION: MAX_WEBHOOK_BODY_BYTES = 2x MAX_FILE_BYTES, matching the
# reviewer's suggestion, to allow for base64 attachment encoding overhead
# (~1.33x) plus JSON/envelope overhead with margin.
MAX_WEBHOOK_BODY_BYTES = 2 * settings.max_file_bytes

# # ASSUMPTION: 60 requests/60s per client IP is a placeholder rate-limit
# budget for the webhook route, generous enough for legitimate Resend
# delivery + retries, tight enough to bound abuse. In-process only — see
# app/policy/rate_limit.py's module docstring for the multi-instance caveat.
_webhook_rate_limiter = RateLimiter(max_requests=60, window_seconds=60)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "env": settings.env, "kill_switch": settings.rowan_kill_switch}


async def _read_body_capped(request: Request, max_bytes: int) -> bytes:
    """Reads the request body incrementally, aborting with 413 as soon as
    the cumulative size exceeds `max_bytes` — never fully buffers an
    oversized body first. Protects even when Content-Length is absent,
    wrong, or the transfer is chunked (a naive `Content-Length` header
    check alone would not)."""
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes:
            raise HTTPException(status_code=413, detail="request body too large")
    return bytes(body)


@app.post("/webhooks/resend/inbound")
async def resend_inbound_webhook(
    request: Request,
    svix_id: str = Header(..., alias="svix-id"),
    svix_timestamp: str = Header(..., alias="svix-timestamp"),
    svix_signature: str = Header(..., alias="svix-signature"),
) -> dict:
    client_key = request.client.host if request.client else "unknown"
    if not await _webhook_rate_limiter.allow(client_key):
        raise HTTPException(status_code=429, detail="rate limit exceeded")

    body = await _read_body_capped(request, MAX_WEBHOOK_BODY_BYTES)

    try:
        result = await handle_inbound_webhook(
            body=body, svix_id=svix_id, svix_timestamp=svix_timestamp, svix_signature=svix_signature
        )
    except WebhookVerificationError:
        # Deliberately generic — do not leak why verification failed.
        raise HTTPException(status_code=401, detail="signature verification failed")
    return result


def _check_internal_token(authorization: str | None) -> None:
    """# ASSUMPTION: internal routes (scheduler trigger) are protected by a
    static bearer token compared in constant time, read from env
    (ROWAN_INTERNAL_TOKEN). In production this route is only ever invoked
    by a trusted cron caller (e.g. Vercel Cron with a secret header) — this
    is a placeholder auth scheme pending that integration, not a public API.
    """
    expected = getattr(settings, "internal_token", "") or ""
    if not expected:
        raise HTTPException(status_code=503, detail="internal endpoint not configured")
    provided = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


@app.post("/internal/scheduler/tick")
async def trigger_scheduler_tick(authorization: str | None = Header(default=None)) -> dict:
    _check_internal_token(authorization)
    stats = await scheduler_tick()
    return stats
