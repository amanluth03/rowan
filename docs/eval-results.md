# Eval results — v1 delivery snapshot

**As of:** `main` @ `0061e86` · 2026-07-18

## Golden-document suite (`tests/evals/`)

Run against real orchestration code (`app.orchestration.runner`) driving a live Dockerized Postgres, with a fixture-scripted fake `ExtractionEngine` (never calls the real Claude API — that's the separately-gated `golden-evals-real` CI tier).

- **18/18 golden document fixtures pass** — full expected trajectory asserted per fixture (state transitions, guardrail trips, tool calls, escalations), not just final output.
- Coverage spans: clean renewals (4), low coverage limits (2), missing additional insured (2), expired policy (1), unparseable/garbage scans (2), retrieval-fallback cases with no requirements on file (2), and **4 adversarial documents with embedded prompt-injection attempts** (fake system banners, fake pre-approval claims, fabricated citations, data-exfiltration requests) — all correctly resisted; none altered the routing decision.
- Full suite: **104 passed, 1 xfailed** (a stale-but-accurate xfail marker in `test_validation_logic.py` tracking a since-fixed bug — flagged for cleanup, not a live gap).
- CI thresholds (`ci/check_thresholds.py`): trajectory pass rate 100%, adversarial-hold rate 100%, faithfulness violations 0, retrieval-fallback correctness 100%.

## Backend test suite

**209/209 passing** against live Postgres (schema, RLS, state machine, all 6 tools, webhook, REST API layer). `ruff check` clean throughout.

## Frontend

`tsc --noEmit`, `eslint`, `next build` all clean. 9/9 unit tests passing (`document-id.test.ts`, the path-traversal-guard regression suite added at security review).

## What this does and doesn't prove

- **Proves:** the orchestration logic, guardrails, validation, faithfulness checks, and routing decisions are correct against a wide, adversarial-inclusive scenario set, exercised through real code.
- **Does not yet prove:** real-world extraction accuracy against the actual Claude API on real (non-synthetic) COI documents at volume — that's the real-model CI tier (`golden-evals-real`, manual-dispatch-gated, requires `ANTHROPIC_API_KEY`), not yet run as part of this delivery since no API key is configured in this environment.

## Security review record

Every chunk of this build went through a dedicated review before merge (never skipped, per `CLAUDE.md`'s policy). Two rounds resulted in a real `BLOCK` that was fixed and re-approved before landing:

| Chunk | Finding | Resolution |
|---|---|---|
| Backend schema/tools/webhook | Path traversal via inbound attachment filename; unbounded/unrate-limited public webhook | Fixed, re-reviewed, approved |
| REST API + gap fixes | Stored-XSS via attacker-controlled `Content-Type` on document download | Fixed, re-reviewed, approved |
| Frontend↔backend wiring | Path-traversal/confused-deputy in document-download proxy | Fixed, re-reviewed, approved |

**Final full-system security audit: APPROVE**, run on Opus, zero downgraded reviews outstanding — see the audit's non-blocking "known limitations" items folded into `docs/what-rowan-does.md` and `backend/README.md`'s known-gaps section.
