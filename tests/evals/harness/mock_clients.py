"""
Deterministic mocks for Claude API and the email provider, used when
ROWAN_EVAL_MODE=mock (the default — fast, offline, no API cost). The
golden-document harness can also run with ROWAN_EVAL_MODE=real against the
actual Claude API (gated separately in CI, see .github/workflows/evals.yml)
to score real extraction accuracy — but that mode never touches Resend; email
sends are ALWAYS mocked in the eval harness, full stop. There is no fixture
or CI path that should ever cause a real outbound email during evals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class RecordedEmail:
    to_email: str
    template_id: str
    template_vars: dict[str, Any]


class MockEmailClient:
    """Records every send; never performs a real network call. Used in both
    mock and real LLM modes — Resend is never live in tests/evals."""

    def __init__(self) -> None:
        self.sent: list[RecordedEmail] = []

    def send(self, *, to_email: str, template_id: str, template_vars: dict[str, Any]) -> dict:
        self.sent.append(RecordedEmail(to_email, template_id, template_vars))
        return {"provider_message_id": f"mock-{len(self.sent)}", "delivery_status": "accepted"}


@dataclass
class MockLLMClient:
    """Returns a pre-programmed response per fixture instead of calling
    Claude. `responses` is keyed by prompt_id (e.g. "classify", "extract",
    "explain") so a fixture can script the full multi-call sequence a
    document goes through in `parsing`/`validating`.

    Each entry is either a dict (returned as-is) or a callable taking the
    rendered prompt text and returning a dict — the callable form lets an
    injection fixture assert on what the mock was actually asked, e.g. that
    the raw document text was delimiter-wrapped rather than concatenated
    directly into an instruction-bearing prompt.
    """

    responses: dict[str, Any] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def complete(self, *, prompt_id: str, prompt_text: str, **kwargs) -> dict:
        self.calls.append({"prompt_id": prompt_id, "prompt_text": prompt_text, **kwargs})
        if prompt_id not in self.responses:
            raise KeyError(
                f"MockLLMClient has no scripted response for prompt_id={prompt_id!r}. "
                f"Fixture must provide one for every prompt step the pipeline invokes."
            )
        resp = self.responses[prompt_id]
        return resp(prompt_text) if callable(resp) else resp


def frozen_clock(now: Any):
    """Returns a zero-arg callable pinned to `now`, matching the
    `PipelineDependencies.now` slot — fixtures need a deterministic "today"
    since RENEWAL_LEAD_DAYS / RESPONSE_DEADLINE_DAYS / expiry checks are
    date-driven (ADR 0002)."""

    def _now():
        return now

    return _now
