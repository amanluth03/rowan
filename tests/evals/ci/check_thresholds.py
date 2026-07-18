#!/usr/bin/env python3
"""
CI gate: reads tests/evals/.results/latest.json (written by conftest.py's
`eval_report` session fixture after a pytest run) and enforces
metrics/thresholds.py. Exit code is the CI signal — separate from pytest's
own exit code, deliberately, so a "no backend yet, everything skipped" run
and a "backend exists, ran for real, and REGRESSED" run are distinguishable
outcomes instead of both just being "pytest exited 0/1".

# ASSUMPTION: while `latest.json` doesn't exist (no golden_document tests
# actually ran and recorded a result — e.g. every one of them hit
# PipelineNotAvailable and was skipped), this script exits 0 with a loud
# "not yet gated" message rather than failing the build. This is a
# deliberate call: CI must stay green through the no-backend-yet period per
# the tech lead's stop condition, but MUST start gating for real the moment
# backend/agent-engineer land the pipeline. Revisit this default the first
# time `latest.json` exists with real (non-skipped) results — at that point
# missing results for a fixture that WAS collected should probably become a
# hard failure instead of a soft skip-notice.
"""
from __future__ import annotations

import argparse
import sys

from tests.evals.metrics import thresholds as th
from tests.evals.metrics.report import EvalRunReport


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail (rather than warn) if latest.json is missing or has zero recorded results. "
             "Use for the gated real-model CI job once backend/agent-engineer code exists.",
    )
    args = parser.parse_args()

    report = EvalRunReport.load()
    if report is None or not report.results:
        msg = "tests/evals/.results/latest.json missing or empty — no golden-document run recorded yet."
        if args.strict:
            print(f"FAIL: {msg}", file=sys.stderr)
            return 1
        print(f"OK (not yet gated): {msg} This is expected until backend/agent-engineer land the pipeline.")
        return 0

    trajectory_results = [r for r in report.results if r.trajectory_passed is not None]
    skipped = [r for r in report.results if r.trajectory_passed is None]
    failures = [r for r in trajectory_results if not r.trajectory_passed]

    print(f"Eval run mode: {report.mode}")
    print(f"Fixtures recorded: {len(report.results)} (skipped: {len(skipped)}, evaluated: {len(trajectory_results)})")

    exit_code = 0

    # --- Trajectory pass rate (safety invariant, 100%) ----------------------
    if trajectory_results:
        pass_rate = sum(1 for r in trajectory_results if r.trajectory_passed) / len(trajectory_results)
        print(f"Trajectory pass rate: {pass_rate:.1%} (threshold: {th.TRAJECTORY_PASS_RATE_MIN:.1%})")
        if pass_rate < th.TRAJECTORY_PASS_RATE_MIN:
            print("FAIL: trajectory pass rate below threshold. Failing fixture(s):", file=sys.stderr)
            for r in failures:
                print(f"  - {r.fixture_id} [{r.category}]: {r.trajectory_failure}", file=sys.stderr)
            exit_code = 1

    # --- Adversarial (injection) hold rate, separately called out ----------
    adversarial_results = [r for r in trajectory_results if r.is_adversarial]
    if adversarial_results:
        held = sum(1 for r in adversarial_results if r.trajectory_passed)
        hold_rate = held / len(adversarial_results)
        print(f"Adversarial (injection) hold rate: {hold_rate:.1%} (threshold: {th.INJECTION_HOLD_RATE_MIN:.1%})")
        if hold_rate < th.INJECTION_HOLD_RATE_MIN:
            print("FAIL: an adversarial/injection fixture did not hold.", file=sys.stderr)
            exit_code = 1

    # --- Field-level extraction accuracy (aggregate, soft-er threshold) ----
    scored = [r for r in trajectory_results if r.field_accuracy is not None]
    if scored:
        agg = sum(r.field_accuracy for r in scored) / len(scored)
        print(f"Field extraction accuracy (aggregate): {agg:.1%} (threshold: {th.FIELD_ACCURACY_MIN:.1%})")
        if agg < th.FIELD_ACCURACY_MIN:
            print("FAIL: field extraction accuracy below threshold.", file=sys.stderr)
            exit_code = 1

    if skipped and not exit_code:
        print(
            f"NOTE: {len(skipped)} fixture(s) were skipped (pipeline/retriever not available). "
            f"Thresholds above are computed only over evaluated fixtures."
        )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
