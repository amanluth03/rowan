"""
Mirrors ADR 0002 (state machine) and the relevant enums from ADR 0001.

`RunState`, `Trigger`, and the reason codes below are copied field-for-field
from the ADRs so fixture authors and the trajectory assertion code share one
vocabulary with the architect's spec. Do not add a state or reason code here
that isn't in an ADR — extend the ADR first.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class RunState(str, Enum):
    """ADR 0001 `run_state` enum / ADR 0002 states, verbatim."""

    MONITORING = "monitoring"
    RENEWAL_DUE_SOON = "renewal_due_soon"
    FIRST_OUTREACH_SENT = "first_outreach_sent"
    AWAITING_VENDOR_RESPONSE = "awaiting_vendor_response"
    DOCUMENT_RECEIVED = "document_received"
    PARSING = "parsing"
    VALIDATING = "validating"
    FILED = "filed"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    ESCALATED_TO_PM = "escalated_to_pm"
    ERRORED = "errored"


# Terminal-for-this-cycle states a document run may legitimately end a test in.
# `filed` loops back to `monitoring`, but for eval purposes we assert the run
# reached `filed` (the interesting endpoint) rather than chase it back around
# the cycle.
TERMINAL_STATES = {
    RunState.FILED,
    RunState.NEEDS_HUMAN_REVIEW,
    RunState.ESCALATED_TO_PM,
    RunState.ERRORED,
}

# States that represent "the agent decided this COI is fine and is done."
# A fixture whose expected trajectory does NOT include these must never
# observe them in the actual trajectory — that's the auto-filed-when-it-
# should-have-escalated failure mode the harness exists to catch.
AUTO_APPROVAL_STATES = {RunState.FILED}


class Trigger(str, Enum):
    SCHEDULER = "scheduler"
    WEBHOOK = "webhook"
    HUMAN = "human"
    TOOL = "tool"
    CODE = "code"  # out-of-allowlist / hard failure -> errored


class ReasonCode(str, Enum):
    """Reason codes named explicitly in the ADRs, plus harness extensions
    flagged inline. Guardrail trips and escalations must use one of these so
    fixtures and assertions share a closed vocabulary."""

    # ADR 0002 / 0005
    NO_CONTACT_EMAIL = "no_contact_email"
    UNCLASSIFIABLE_DOCUMENT = "unclassifiable_document"
    LOW_CONFIDENCE_EXTRACTION = "low_confidence_extraction"
    NO_REQUIREMENTS_ON_FILE = "no_requirements_on_file"
    NO_RESPONSE = "no_response"
    BAD_CONTACT_EMAIL = "bad_contact_email"
    REJECTED_BY_PM = "rejected_by_pm"

    # ADR 0004 mark_task_complete precondition mismatch
    COMPLETION_PRECONDITION_UNMET = "completion_precondition_unmet"

    # ADR 0004 parse_document: "injection/oversized/wrong-type caught
    # pre-LLM -> denied + guardrail event" — the ADR doesn't name a specific
    # reason code for this, so the harness names one.
    # ASSUMPTION: no ADR gives pre-LLM guardrail trips a specific reason_code
    # name; using `pre_llm_guardrail_triggered` with a `detail` sub-reason
    # (e.g. "prompt_injection_pattern", "oversized_file", "disallowed_type").
    # Confirm/rename with agent-engineer once they land the actual guardrail
    # module, and update this enum to match rather than the other way round.
    PRE_LLM_GUARDRAIL_TRIGGERED = "pre_llm_guardrail_triggered"

    # Faithfulness (ADR 0005) failing independent of pass/fail coverage.
    FAITHFULNESS_VIOLATION = "faithfulness_violation"

    # Out-of-allowlist action (ADR 0002 global rule).
    OUT_OF_ALLOWLIST_ACTION = "out_of_allowlist_action"

    # ADR 0002's `validating -> needs_human_review` guard fires on
    # "result='fail' ... (reason from coi_validations.flags)" — i.e. the ADR
    # deliberately does NOT name one fixed reason code for a coverage-line
    # failure, it points at the dynamic `flags` list instead.
    # ASSUMPTION: the harness still needs one stable top-level reason_code to
    # populate the `escalations` row's `reason_code` column for THIS
    # escalation kind, distinct from the more specific fixed codes above
    # (no_requirements_on_file, low_confidence_extraction, etc). Using
    # `validation_failed` as that generic code, with the specific line-level
    # reasons asserted separately via `ExpectedTrajectory.
    # expected_validation_flags` against `coi_validations.flags`. Confirm
    # naming with backend-engineer once coi_validations.flags values are
    # actually defined.
    VALIDATION_FAILED = "validation_failed"


class StateTransition(BaseModel):
    from_state: Optional[RunState]
    to_state: RunState
    trigger: Trigger
    guard: str  # human-readable guard name, e.g. "extraction_confident_and_valid"


class GuardrailTrip(BaseModel):
    reason_code: ReasonCode
    severity: str = "warn"  # ADR 0001 event_severity: info|warn|error
    detail: dict[str, Any] = Field(default_factory=dict)


class EscalationRecord(BaseModel):
    kind: str  # ADR 0001 escalation_kind: needs_human_review | escalated_to_pm
    reason_code: ReasonCode
    resolution: Optional[str] = None  # approved|rejected|revision_requested|acknowledged


class ToolCallRecord(BaseModel):
    tool_name: str
    status: str  # ok | denied | failed (ADR 0004 common envelope)
    idempotent_replay: bool = False
    data: dict[str, Any] = Field(default_factory=dict)


class RunTrajectory(BaseModel):
    """What the harness expects `PipelineUnderTest` to return: the full,
    observable record of one document's trip through the pipeline, shaped
    like the `agent_events` rows it should have produced."""

    run_id: str
    states: list[StateTransition]
    guardrail_trips: list[GuardrailTrip] = Field(default_factory=list)
    escalations: list[EscalationRecord] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    final_state: RunState
    # Flat dict of the extraction pass's output fields (same key shape as a
    # fixture's `expected_extraction`), for field-accuracy scoring only. None
    # when extraction never ran or never produced usable output (e.g. the
    # document never reached `parsing`, or `parsing` failed outright).
    extracted_fields: Optional[dict[str, Any]] = None

    @property
    def state_sequence(self) -> list[RunState]:
        seq: list[RunState] = []
        for t in self.states:
            if not seq or seq[-1] != t.to_state:
                seq.append(t.to_state)
        return seq

    @property
    def tool_names_called(self) -> list[str]:
        return [tc.tool_name for tc in self.tool_calls]


class ExpectedTrajectory(BaseModel):
    """What a fixture author asserts SHOULD happen. Compared against a real
    `RunTrajectory` by `harness/trajectory_assert.py`."""

    entry_state: RunState = RunState.DOCUMENT_RECEIVED
    # Ordered states the run must pass through, in order (subsequence match:
    # extra transitions the real implementation adds are fine as long as
    # these appear in this relative order).
    expected_state_sequence: list[RunState]
    expected_final_state: RunState
    # States that must NEVER appear in the actual trajectory. Always include
    # AUTO_APPROVAL_STATES-derived states here for any fixture whose expected
    # final state isn't `filed` — this is what turns "auto-filed instead of
    # escalated" into a hard failure rather than a passed field-accuracy check.
    forbidden_states: list[RunState] = Field(default_factory=list)
    expected_guardrail_trips: list[ReasonCode] = Field(default_factory=list)
    expected_escalation: Optional[EscalationRecord] = None
    # Tool names that must be called at least once (order not enforced here).
    expected_tool_calls: list[str] = Field(default_factory=list)
    # Tool calls that must NEVER occur (e.g. file_document/mark_task_complete
    # on a fixture that must not be auto-approved).
    forbidden_tool_calls: list[str] = Field(default_factory=list)
    # If mark_task_complete is expected, what basis it must be completed on
    # (ADR 0004: validation_passed | human_approved). None = not expected to
    # complete at all in this fixture's trajectory.
    expected_completion_basis: Optional[str] = None
    expected_faithfulness_ok: Optional[bool] = None
    # Document-level flag codes (`coi_validations.flags[i]["code"]` per the
    # real `app.tools.validation_logic.evaluate_validation` shape — e.g.
    # "policy_expired", "low_confidence_extraction", "unverified_requirement",
    # "no_requirements_on_file", "missing_expiration_date"). NOT per-line
    # coverage failures — those are `expected_line_reasons` below. Checked as
    # a subset, not exact match.
    expected_validation_flags: list[str] = Field(default_factory=list)
    # Per-coverage-type line-level failure reasons
    # (`line_results[i]["reasons"]` in the real shape, e.g.
    # {"general_liability": ["each_occurrence_below_minimum",
    # "missing_additional_insured"]}). Checked as a subset per coverage type.
    expected_line_reasons: dict[str, list[str]] = Field(default_factory=dict)
