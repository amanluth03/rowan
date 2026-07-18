"""
Structural faithfulness check per ADR 0005: "no asserted requirement in
output without a matching retrieved ID." This is enforced by construction
(IDs in, IDs out), not by trusting the validator's `faithfulness_ok` flag —
the whole point of this module is to be a check the harness runs
INDEPENDENTLY of whatever the validation code claims about itself, so a
buggy validator that sets `faithfulness_ok=True` while asserting an unbacked
requirement gets caught here regardless.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from tests.evals.contracts.retrieval import RetrievalResult
from tests.evals.contracts.validation import CoiValidation


@dataclass
class FaithfulnessCheckResult:
    ok: bool
    unbacked_line_ids: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def check_faithfulness(retrieval: RetrievalResult, validation: CoiValidation) -> FaithfulnessCheckResult:
    """IDs-in/IDs-out structural check: every `source_compliance_requirement_id`
    referenced in `validation.line_results` must be present in
    `retrieval.requirements`'s id set. A None id (PM override with no KB
    backing, ADR 0001) is ALSO unfaithful — it must have been flagged
    'unverified requirement' upstream and routed to escalation, not asserted
    as a validated line."""
    retrieved_ids = {str(r.id) for r in retrieval.requirements}
    unbacked: list[str] = []
    reasons: list[str] = []

    for line in validation.line_results:
        src_id = line.source_compliance_requirement_id
        if src_id is None:
            unbacked.append(str(line.vendor_coverage_requirement_id))
            reasons.append(
                f"line for {line.coverage_type} (vendor_coverage_requirement_id="
                f"{line.vendor_coverage_requirement_id}) has no source_compliance_requirement_id "
                f"(unverified PM override) but was asserted in validation output."
            )
            continue
        if str(src_id) not in retrieved_ids:
            unbacked.append(str(src_id))
            reasons.append(
                f"line for {line.coverage_type} cites source_compliance_requirement_id="
                f"{src_id}, which is not in the retrieved set {sorted(retrieved_ids)}."
            )

    ok = not unbacked
    if ok and not validation.faithfulness_ok:
        # The validator flagged itself unfaithful even though our structural
        # check found nothing unbacked. Don't silently prefer either signal —
        # surface the disagreement; a fixture author or backend bug needs to
        # look at it.
        reasons.append(
            "structural check found no unbacked lines, but validation.faithfulness_ok=False. "
            "Investigate — either the structural check is missing a case, or the validator "
            "is over-flagging."
        )
        ok = False
    if not ok and validation.faithfulness_ok:
        reasons.append(
            "validation.faithfulness_ok=True but structural check found unbacked line(s) — "
            "this is exactly the bug ADR 0005's faithfulness check exists to catch."
        )

    return FaithfulnessCheckResult(ok=ok, unbacked_line_ids=unbacked, reasons=reasons)
