"""Unit tests for `ClaudeExplanationEngine` (app/tools/explanation_engine.py)
— fully offline, Anthropic client monkeypatched. Covers: retry, refusal
handling, and empty-response rejection (this call is descriptive-only, but
"descriptive-only" must still mean "schema/content validated", not "throw
away and guess if it comes back wrong")."""

from __future__ import annotations

from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app.tools.draft_explanation import ExplanationEngineError
from app.tools.explanation_engine import ClaudeExplanationEngine


def _engine() -> ClaudeExplanationEngine:
    return ClaudeExplanationEngine(api_key="test-key-not-real")


def _text_response(text: str, *, stop_reason="end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=50, output_tokens=20),
        stop_reason=stop_reason,
    )


def _connection_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))


async def test_drafts_explanation_from_deterministic_flags(monkeypatch):
    engine = _engine()

    async def fake_create(**kwargs):
        assert "re-evaluate" in kwargs["system"] or "already been decided" in kwargs["system"]
        return _text_response("Coverage is short on general liability — the vendor should resend.")

    monkeypatch.setattr(engine._client.messages, "create", fake_create)

    result = await engine.draft(
        vendor_name="Acme Plumbing",
        result="fail",
        line_results=[{"coverage_type": "general_liability", "pass": False, "reasons": ["each_occurrence_below_minimum"]}],
        flags=[{"code": "each_occurrence_below_minimum", "severity": "high"}],
        faithfulness_ok=True,
        extraction_notes=None,
    )
    assert "general liability" in result.explanation_text
    assert result.cost_cents >= 0


async def test_retries_once_then_succeeds(monkeypatch):
    engine = _engine()
    calls = {"n": 0}

    async def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _connection_error()
        return _text_response("Looks fine after retry.")

    monkeypatch.setattr(engine._client.messages, "create", flaky)
    result = await engine.draft(
        vendor_name="Acme", result="pass", line_results=[], flags=[], faithfulness_ok=True, extraction_notes=None
    )
    assert calls["n"] == 2
    assert result.explanation_text == "Looks fine after retry."


async def test_refusal_raises_explanation_engine_error(monkeypatch):
    engine = _engine()

    async def refused(**kwargs):
        return _text_response("", stop_reason="refusal")

    monkeypatch.setattr(engine._client.messages, "create", refused)
    with pytest.raises(ExplanationEngineError):
        await engine.draft(
            vendor_name="Acme", result="fail", line_results=[], flags=[], faithfulness_ok=True, extraction_notes=None
        )


async def test_empty_text_raises_rather_than_silently_returning_blank(monkeypatch):
    engine = _engine()

    async def empty(**kwargs):
        return _text_response("   ")

    monkeypatch.setattr(engine._client.messages, "create", empty)
    with pytest.raises(ExplanationEngineError):
        await engine.draft(
            vendor_name="Acme", result="fail", line_results=[], flags=[], faithfulness_ok=True, extraction_notes=None
        )


def test_missing_api_key_fails_closed_at_construction():
    with pytest.raises(ExplanationEngineError):
        ClaudeExplanationEngine(api_key="")
