"""
Field-level extraction accuracy scoring. Compares a fixture's hand-labeled
`expected_extraction` dict against the pipeline's actual extracted fields.
Deliberately independent of trajectory correctness (contracts/state_machine
+ trajectory_assert.py own that) — this module only ever answers "did the
LLM read the numbers off the document correctly," never "did the machine do
the right thing with those numbers."

# ASSUMPTION: scoring is per-field exact-match after light normalization
# (case-fold strings, int-compare dollar amounts, date-compare ISO strings).
# No fuzzy/semantic matching in v1 — coverage limits and dates are exact-or-
# wrong facts, and fuzzy matching would hide real extraction bugs. Revisit if
# real-world OCR noise makes exact-match too punishing once agent-engineer's
# actual prompt is scored against real scans.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


def _normalize(v: Any) -> Any:
    if isinstance(v, str):
        return v.strip().casefold()
    if isinstance(v, date):
        return v.isoformat()
    return v


@dataclass
class FieldAccuracyReport:
    fixture_id: str
    total_fields: int
    correct_fields: int
    mismatches: list[dict] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct_fields / self.total_fields if self.total_fields else 1.0


def score_extraction(fixture_id: str, expected: dict[str, Any], actual: dict[str, Any]) -> FieldAccuracyReport:
    """Flat dict comparison. Fixtures store `expected_extraction` as a flat
    dict of dotted keys (e.g. "coverage.general_liability.each_occurrence")
    so nested COI structure doesn't need a recursive differ here."""
    mismatches = []
    correct = 0
    for k, expected_v in expected.items():
        actual_v = actual.get(k, "<<MISSING>>")
        if _normalize(actual_v) == _normalize(expected_v):
            correct += 1
        else:
            mismatches.append({"field": k, "expected": expected_v, "actual": actual_v})
    return FieldAccuracyReport(
        fixture_id=fixture_id,
        total_fields=len(expected),
        correct_fields=correct,
        mismatches=mismatches,
    )


def aggregate_accuracy(reports: list[FieldAccuracyReport]) -> float:
    total = sum(r.total_fields for r in reports)
    correct = sum(r.correct_fields for r in reports)
    return correct / total if total else 1.0
