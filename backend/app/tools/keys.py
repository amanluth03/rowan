"""Deterministic idempotency-key builders, one per tool, matching ADR 0004's
"Idempotency key" line for each tool EXACTLY. Centralized here so the key
shape is defined once and callers can't accidentally drift the format
between, say, the orchestration runner and a test fixture.
"""

from __future__ import annotations

import hashlib
from uuid import UUID


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# Backwards-compatible alias for internal call sites written against the
# original private name.
_sha256 = sha256


def send_email_key(run_id: UUID, template_id: str, outreach_sequence_no: int | str) -> str:
    # int for vendor-outreach sends (0-indexed outreach attempt number);
    # str for PM-directed notices, where the caller (e.g. escalate_to_pm)
    # passes a stable discriminator such as reason_code so distinct
    # escalation reasons within the same run each get their own key while
    # re-firing the SAME reason+state stays a pure idempotent replay.
    return _sha256(f"{run_id}|{template_id}|{outreach_sequence_no}")


def parse_document_key(coi_document_id: UUID, prompt_id: str, attempt_no: int) -> str:
    return _sha256(f"{coi_document_id}|{prompt_id}|{attempt_no}")


def validate_key(coi_extraction_id: UUID) -> str:
    return _sha256(f"{coi_extraction_id}|validate")


def file_document_key(coi_document_id: UUID) -> str:
    return _sha256(f"{coi_document_id}|file")


def escalate_key(run_id: UUID, reason_code: str, run_state: str) -> str:
    return _sha256(f"{run_id}|{reason_code}|{run_state}")


def mark_task_complete_key(run_id: UUID, coi_validation_id: UUID) -> str:
    return _sha256(f"{run_id}|{coi_validation_id}|complete")
