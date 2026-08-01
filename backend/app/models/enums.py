"""Python mirrors of the Postgres native enums (migrations/0002_enums.sql).

Kept as plain `str, Enum` so they serialize cleanly to/from asyncpg (which
hands back enum columns as plain strings) and Pydantic JSON alike.
"""

from __future__ import annotations

from enum import Enum


class CoverageType(str, Enum):
    general_liability = "general_liability"
    auto_liability = "auto_liability"
    workers_comp = "workers_comp"
    umbrella_excess = "umbrella_excess"
    professional_liability = "professional_liability"
    pollution = "pollution"
    employers_liability = "employers_liability"


class VendorRole(str, Enum):
    plumber = "plumber"
    electrician = "electrician"
    hvac = "hvac"
    general_contractor = "general_contractor"
    landscaper = "landscaper"
    roofer = "roofer"
    cleaner = "cleaner"
    pest_control = "pest_control"
    other = "other"


class PropertyType(str, Enum):
    single_family = "single_family"
    multi_family = "multi_family"
    condo = "condo"
    commercial = "commercial"
    mixed_use = "mixed_use"


class RunState(str, Enum):
    monitoring = "monitoring"
    renewal_due_soon = "renewal_due_soon"
    first_outreach_sent = "first_outreach_sent"
    awaiting_vendor_response = "awaiting_vendor_response"
    document_received = "document_received"
    parsing = "parsing"
    validating = "validating"
    filed = "filed"
    needs_human_review = "needs_human_review"
    escalated_to_pm = "escalated_to_pm"
    errored = "errored"


class RunStatus(str, Enum):
    active = "active"
    paused = "paused"
    completed = "completed"
    errored = "errored"


class EventType(str, Enum):
    state_transition = "state_transition"
    tool_call = "tool_call"
    llm_call = "llm_call"
    guardrail_trip = "guardrail_trip"
    human_intervention = "human_intervention"
    error = "error"
    note = "note"


class EventSeverity(str, Enum):
    info = "info"
    warn = "warn"
    error = "error"


class DocStatus(str, Enum):
    received = "received"
    parsing = "parsing"
    parsed = "parsed"
    filed = "filed"
    rejected = "rejected"
    superseded = "superseded"


class DocSource(str, Enum):
    email_inbound = "email_inbound"
    manual_upload = "manual_upload"
    onboarding_import = "onboarding_import"


class EmailDirection(str, Enum):
    outbound = "outbound"
    inbound = "inbound"


class EscalationKind(str, Enum):
    needs_human_review = "needs_human_review"
    escalated_to_pm = "escalated_to_pm"


class EscalationStatus(str, Enum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"


class ValidationResult(str, Enum):
    pass_ = "pass"
    fail = "fail"


class ToolInvocationStatus(str, Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"


class UserRole(str, Enum):
    owner = "owner"
    assistant = "assistant"


class VendorStatus(str, Enum):
    active = "active"
    inactive = "inactive"


class ToolStatus(str, Enum):
    """Tool output envelope status (ADR 0004): ok | denied | failed.

    NOT a DB enum — this is the Tools-layer (layer 3) return contract.
    """

    ok = "ok"
    denied = "denied"
    failed = "failed"
