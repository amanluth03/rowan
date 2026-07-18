"""The structured COI extraction schema — the CONTRACT between
agent-engineer's `parse_document` LLM extraction (writes this shape into
`coi_extractions.extracted`) and backend-engineer's deterministic validator
(`app/tools/validation_logic.py`, which reads this shape back out).

Backend-engineer owns this file because the deterministic comparison logic
is backend-engineer's to implement (per the build brief: "the deterministic
pass/fail logic itself... is yours to implement; only the extraction is
agent-engineer's"), and that comparison needs a concrete typed shape to
compare against `vendor_coverage_requirements`. agent-engineer's extraction
prompt/parsing code should import and produce exactly this shape — see
`app/tools/parse_document.py`'s `ExtractionEngine` Protocol for the call
site this feeds.

Field-level `confidence` is required on every coverage line and at the
top level (`overall_confidence`) because the post-LLM guardrail
(CLAUDE.md: "any field failing schema or sub-threshold confidence ->
needs_human_review, never guessed") is enforced by the ORCHESTRATION layer
reading `overall_confidence` against `CONFIDENCE_THRESHOLD` — the schema
must carry confidence for that check to be possible at all.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.models.enums import CoverageType


class ExtractedCoverageLine(BaseModel):
    coverage_type: CoverageType
    each_occurrence: int | None = Field(default=None, description="Whole-dollar limit, per ADR 0000 money convention.")
    aggregate: int | None = None
    additional_insured: bool | None = None
    waiver_of_subrogation: bool | None = None
    primary_noncontributory: bool | None = None
    # Per-line extraction confidence, 0..1. None is treated as 0 (low
    # confidence) by the validator — a line the model didn't score is never
    # trusted by default.
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractedCoiFields(BaseModel):
    """The full structured extraction of one COI document."""

    insured_name_on_certificate: str | None = None
    policy_effective_date: date | None = None
    policy_expiration_date: date | None = None
    coverage_lines: list[ExtractedCoverageLine] = Field(default_factory=list)
    # Any free-text caveats the model wants to surface to a human reviewer.
    # Descriptive only — per CLAUDE.md/ADR 0004, this NEVER changes routing.
    notes: str | None = None
    overall_confidence: float = Field(ge=0.0, le=1.0)
