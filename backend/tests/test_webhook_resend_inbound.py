"""TDD: inbound-email webhook — signature verification, reply_token
resolution (reply_token -> run -> organization_id, per ADR 0001's RLS
section), and idempotency against provider replay.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import date, timedelta

import pytest

from app.db import org_scoped_tx
from app.models.coi_fields import ExtractedCoiFields, ExtractedCoverageLine
from app.models.enums import CoverageType, RunState
from app.retrieval import run_repo
from app.tools.parse_document import ExtractionEngineResult
from app.webhooks.resend_inbound import WebhookVerificationError, handle_inbound_webhook, verify_signature


class _FakeEngine:
    """Test double for agent-engineer's ExtractionEngine (see
    app/tools/parse_document.py's documented interface) — returns a
    caller-supplied ExtractedCoiFields for both the classify and extract
    sub-passes instead of calling Claude."""

    def __init__(self, extracted: ExtractedCoiFields) -> None:
        self.extracted = extracted

    async def extract(self, *, document_bytes, content_type, prompt_id, attempt_no):
        return ExtractionEngineResult(
            extracted=self.extracted,
            field_confidence={},
            model="fake-model",
            prompt_hash="fakehash",
            input_tokens=10,
            output_tokens=10,
            cost_cents=1,
        )

pytestmark = pytest.mark.asyncio

SECRET = "whsec_dGVzdF9zZWNyZXRfa2V5X2Zvcl90ZXN0cw=="  # base64-ish test secret


def _sign(secret: str, svix_id: str, svix_timestamp: str, body: bytes) -> str:
    signed_content = f"{svix_id}.{svix_timestamp}.{body.decode()}"
    key = base64.b64decode(secret.split("_", 1)[1] + "==") if "_" in secret else secret.encode()
    sig = hmac.new(key, signed_content.encode(), hashlib.sha256).digest()
    return "v1," + base64.b64encode(sig).decode()


class TestSignatureVerification:
    # Not async, but harmless under the module-level asyncio mark (pytest-asyncio
    # simply ignores sync test functions when a mark is applied via pytestmark).

    def test_valid_signature_passes(self):
        body = b'{"hello":"world"}'
        svix_id = "msg_1"
        svix_ts = "1700000000"
        sig = _sign(SECRET, svix_id, svix_ts, body)
        assert verify_signature(secret=SECRET, svix_id=svix_id, svix_timestamp=svix_ts, body=body, svix_signature=sig) is True

    def test_tampered_body_fails(self):
        body = b'{"hello":"world"}'
        svix_id = "msg_1"
        svix_ts = "1700000000"
        sig = _sign(SECRET, svix_id, svix_ts, body)
        tampered = b'{"hello":"tampered"}'
        with pytest.raises(WebhookVerificationError):
            assert verify_signature(secret=SECRET, svix_id=svix_id, svix_timestamp=svix_ts, body=tampered, svix_signature=sig)

    def test_wrong_secret_fails(self):
        body = b'{"hello":"world"}'
        svix_id = "msg_1"
        svix_ts = "1700000000"
        sig = _sign("whsec_wrongwrongwrongwrongwrongwrongwrong==", svix_id, svix_ts, body)
        with pytest.raises(WebhookVerificationError):
            verify_signature(secret=SECRET, svix_id=svix_id, svix_timestamp=svix_ts, body=body, svix_signature=sig)


class TestHandleInboundWebhook:
    async def test_resolves_reply_token_and_advances_run(self, org_and_vendor, make_run, monkeypatch):
        from app import config as config_module

        run_id = await make_run(state="awaiting_vendor_response", due_date=date.today())
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            run = await run_repo.get_run(conn, run_id)
        reply_token = run.reply_token

        monkeypatch.setattr(config_module.settings, "resend_webhook_secret", SECRET)

        payload = {
            "type": "email.received",
            "data": {
                "to": [f"{reply_token}@reply.rowan.example.com"],
                "from": "vendor@example.com",
                "subject": "Re: COI renewal",
                "attachments": [
                    {
                        "filename": "coi.pdf",
                        "content_type": "application/pdf",
                        "content_base64": base64.b64encode(b"%PDF-1.4\n" + b"0" * 100).decode(),
                    }
                ],
            },
        }
        body = json.dumps(payload).encode()
        svix_id = f"msg_test_1_{run_id}"
        svix_ts = "1700000000"
        sig = _sign(SECRET, svix_id, svix_ts, body)

        result = await handle_inbound_webhook(
            body=body, svix_id=svix_id, svix_timestamp=svix_ts, svix_signature=sig
        )
        assert result["status"] == "processed"

        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            run = await run_repo.get_run(conn, run_id)
        assert run.state == RunState.parsing  # cascaded document_received -> parsing

    async def test_full_cascade_reaches_monitoring_with_no_manual_intervention(
        self, org_and_vendor, make_run, monkeypatch
    ):
        """Regression test for the coordinator/qa-evals-engineer finding #1
        (2026-07-18, severe): "Nothing in the production code path ever
        drives parsing -> validating -> filed." Simulates a REAL inbound
        webhook delivery carrying a clean, passing COI and asserts the run
        reaches `monitoring` (the full document_received -> parsing ->
        validating -> filed -> monitoring cascade) from ONE webhook call —
        no scheduler tick, no human action, no second call of any kind.
        """
        from app import config as config_module

        run_id = await make_run(state="awaiting_vendor_response", due_date=date.today())
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            run = await run_repo.get_run(conn, run_id)
        reply_token = run.reply_token

        monkeypatch.setattr(config_module.settings, "resend_webhook_secret", SECRET)

        clean_extraction = ExtractedCoiFields(
            policy_effective_date=date(2026, 1, 1),
            policy_expiration_date=date(2027, 1, 1),
            coverage_lines=[
                ExtractedCoverageLine(
                    coverage_type=CoverageType.general_liability,
                    each_occurrence=1_000_000,
                    aggregate=2_000_000,
                    additional_insured=True,
                    confidence=0.95,
                )
            ],
            overall_confidence=0.95,
        )

        payload = {
            "type": "email.received",
            "data": {
                "to": [f"{reply_token}@reply.rowan.example.com"],
                "from": "vendor@example.com",
                "subject": "Re: COI renewal",
                "attachments": [
                    {
                        "filename": "coi.pdf",
                        "content_type": "application/pdf",
                        "content_base64": base64.b64encode(b"%PDF-1.4\n" + b"0" * 100).decode(),
                    }
                ],
            },
        }
        body = json.dumps(payload).encode()
        svix_id = f"msg_cascade_pass_{run_id}"
        svix_ts = "1700000000"
        sig = _sign(SECRET, svix_id, svix_ts, body)

        result = await handle_inbound_webhook(
            body=body,
            svix_id=svix_id,
            svix_timestamp=svix_ts,
            svix_signature=sig,
            engine=_FakeEngine(clean_extraction),
        )
        assert result["status"] == "processed"

        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            run = await run_repo.get_run(conn, run_id)
        assert run.state == RunState.monitoring, (
            f"expected the run to cascade all the way to a terminal state "
            f"(monitoring) with no manual intervention; stalled in {run.state}"
        )
        # Cycle actually reset for the next renewal (complete_filing's job).
        assert run.due_date == date(2027, 1, 1) - timedelta(days=30)

        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            filed_doc = await conn.fetchrow(
                "select is_current, valid_from, valid_to from coi_documents where vendor_id = $1",
                org_and_vendor["vendor_id"],
            )
        assert filed_doc["is_current"] is True
        assert filed_doc["valid_to"] == date(2027, 1, 1)

    async def test_full_cascade_stops_at_needs_human_review_on_failing_coverage(
        self, org_and_vendor, make_run, monkeypatch
    ):
        """Same cascade, but with coverage that fails validation (limit far
        below the vendor's requirement) — must stop at `needs_human_review`,
        never silently file a failing COI."""
        from app import config as config_module

        run_id = await make_run(state="awaiting_vendor_response", due_date=date.today())
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            run = await run_repo.get_run(conn, run_id)
        reply_token = run.reply_token

        monkeypatch.setattr(config_module.settings, "resend_webhook_secret", SECRET)

        failing_extraction = ExtractedCoiFields(
            policy_effective_date=date(2026, 1, 1),
            policy_expiration_date=date(2027, 1, 1),
            coverage_lines=[
                ExtractedCoverageLine(
                    coverage_type=CoverageType.general_liability,
                    each_occurrence=100,  # far below the 1,000,000 minimum
                    aggregate=100,
                    additional_insured=True,
                    confidence=0.95,
                )
            ],
            overall_confidence=0.95,
        )

        payload = {
            "type": "email.received",
            "data": {
                "to": [f"{reply_token}@reply.rowan.example.com"],
                "from": "vendor@example.com",
                "subject": "Re: COI renewal",
                "attachments": [
                    {
                        "filename": "coi.pdf",
                        "content_type": "application/pdf",
                        "content_base64": base64.b64encode(b"%PDF-1.4\n" + b"0" * 100).decode(),
                    }
                ],
            },
        }
        body = json.dumps(payload).encode()
        svix_id = f"msg_cascade_fail_{run_id}"
        svix_ts = "1700000000"
        sig = _sign(SECRET, svix_id, svix_ts, body)

        result = await handle_inbound_webhook(
            body=body,
            svix_id=svix_id,
            svix_timestamp=svix_ts,
            svix_signature=sig,
            engine=_FakeEngine(failing_extraction),
        )
        assert result["status"] == "processed"

        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            run = await run_repo.get_run(conn, run_id)
        assert run.state == RunState.needs_human_review

        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            escalations = await conn.fetch("select * from escalations where run_id = $1", run_id)
        assert len(escalations) == 1
        assert escalations[0]["kind"] == "needs_human_review"

    async def test_unknown_reply_token_is_rejected_safely(self, monkeypatch):
        from app import config as config_module

        monkeypatch.setattr(config_module.settings, "resend_webhook_secret", SECRET)
        payload = {
            "type": "email.received",
            "data": {
                "to": ["tok_does_not_exist@reply.rowan.example.com"],
                "from": "vendor@example.com",
                "subject": "x",
                "attachments": [],
            },
        }
        body = json.dumps(payload).encode()
        svix_id = f"msg_test_2_{__import__('uuid').uuid4()}"
        svix_ts = "1700000000"
        sig = _sign(SECRET, svix_id, svix_ts, body)

        result = await handle_inbound_webhook(
            body=body, svix_id=svix_id, svix_timestamp=svix_ts, svix_signature=sig
        )
        assert result["status"] == "ignored"

    async def test_replay_of_same_webhook_is_idempotent(self, org_and_vendor, make_run, monkeypatch):
        from app import config as config_module

        run_id = await make_run(state="awaiting_vendor_response", due_date=date.today())
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            run = await run_repo.get_run(conn, run_id)
        reply_token = run.reply_token

        monkeypatch.setattr(config_module.settings, "resend_webhook_secret", SECRET)

        payload = {
            "type": "email.received",
            "data": {
                "to": [f"{reply_token}@reply.rowan.example.com"],
                "from": "vendor@example.com",
                "subject": "Re: COI renewal",
                "attachments": [
                    {
                        "filename": "coi.pdf",
                        "content_type": "application/pdf",
                        "content_base64": base64.b64encode(b"%PDF-1.4\n" + b"0" * 100).decode(),
                    }
                ],
            },
        }
        body = json.dumps(payload).encode()
        svix_id = f"msg_test_3_{run_id}"
        svix_ts = "1700000000"
        sig = _sign(SECRET, svix_id, svix_ts, body)

        r1 = await handle_inbound_webhook(body=body, svix_id=svix_id, svix_timestamp=svix_ts, svix_signature=sig)
        r2 = await handle_inbound_webhook(body=body, svix_id=svix_id, svix_timestamp=svix_ts, svix_signature=sig)
        assert r1["status"] == "processed"
        assert r2["status"] == "replayed"

        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            docs = await conn.fetch("select * from coi_documents where run_id = $1", run_id)
        assert len(docs) == 1  # not double-stored
