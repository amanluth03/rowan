"""Tests for app/policy/file_guardrails.py — pre-LLM attachment validation.
Includes the security-reviewer's blocking finding (path traversal via
inbound attachment filename): the extension check alone let a filename like
`../../../../tmp/evil.pdf` through, since it only inspects text after the
last `.`. Hardened here to reject path separators / `..` / NUL outright, as
defense-in-depth on top of the real fix (storage path is derived from
document_id + detected type, never the raw filename — see
app/orchestration/runner.py and tests/test_orchestration_document_pipeline.py).
"""

from __future__ import annotations

from app.policy.file_guardrails import check_attachment

PDF_MAGIC = b"%PDF-1.4\n" + b"0" * 100


class TestPathTraversalRejection:
    def test_rejects_unix_path_traversal(self):
        result = check_attachment(filename="../../../../tmp/evil.pdf", data=PDF_MAGIC)
        assert result.ok is False
        assert result.reason == "unsafe_filename"

    def test_rejects_absolute_path(self):
        result = check_attachment(filename="/etc/passwd.pdf", data=PDF_MAGIC)
        assert result.ok is False
        assert result.reason == "unsafe_filename"

    def test_rejects_embedded_path_separator(self):
        result = check_attachment(filename="subdir/coi.pdf", data=PDF_MAGIC)
        assert result.ok is False
        assert result.reason == "unsafe_filename"

    def test_rejects_windows_style_separator(self):
        result = check_attachment(filename="..\\..\\windows\\evil.pdf", data=PDF_MAGIC)
        assert result.ok is False
        assert result.reason == "unsafe_filename"

    def test_rejects_dot_dot_even_without_separator(self):
        result = check_attachment(filename="..pdf", data=PDF_MAGIC)
        assert result.ok is False
        assert result.reason == "unsafe_filename"

    def test_rejects_nul_byte(self):
        result = check_attachment(filename="coi.pdf\x00.exe", data=PDF_MAGIC)
        assert result.ok is False
        assert result.reason == "unsafe_filename"

    def test_ordinary_filename_still_accepted(self):
        result = check_attachment(filename="certificate_of_insurance.pdf", data=PDF_MAGIC)
        assert result.ok is True
        assert result.detected_type == "pdf"


class TestExistingChecksStillWork:
    def test_empty_attachment_rejected(self):
        result = check_attachment(filename="coi.pdf", data=b"")
        assert result.ok is False
        assert result.reason == "empty_attachment"

    def test_disallowed_extension_rejected(self):
        result = check_attachment(filename="coi.exe", data=PDF_MAGIC)
        assert result.ok is False
        assert result.reason == "disallowed_extension"

    def test_extension_content_mismatch_rejected(self):
        result = check_attachment(filename="coi.pdf", data=b"\x89PNG\r\n\x1a\n" + b"0" * 100)
        assert result.ok is False
        assert "extension_content_mismatch" in result.reason
