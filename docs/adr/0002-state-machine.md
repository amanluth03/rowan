# ADR 0002 — Renewal state machine spec

**Status:** Proposed
**Layer:** Orchestration (this IS the planner; there is no free-roaming loop)
**Depends on:** 0001 (`runs`, `agent_events`). Feeds: 0004 (tools), 0005 (retrieval).

## Decision

The renewal workflow is a deterministic, persisted state machine. One
long-lived run per active vendor (`runs`, partial-unique on active vendor). The
run cycles: `monitoring → … → filed → monitoring` for the next expiry. State
lives in `runs.state`; every transition writes an `agent_events` row
(`event_type='state_transition'`, `from_state`, `to_state`, guard name).

**The machine, not the LLM, decides transitions.** The LLM is invoked only at
two bounded decision points, and neither decides an outcome:
1. **Extraction** (in `parsing`) — reads the document, emits structured fields.
2. **Coverage-gap explanation drafting** (in `validating`/`needs_human_review`) —
   turns deterministic validation flags into human-readable prose.

### Config constants (all configurable; org-overridable via `organizations.settings`)

```
RENEWAL_LEAD_DAYS      = 30    # when monitoring → renewal_due_soon
FOLLOWUP_INTERVAL_DAYS = 4     # min gap between outreach emails
MAX_OUTREACH           = 3     # hard cap, outreach emails per run cycle
MAX_LLM_PER_DOC        = 5     # hard cap, LLM calls per document
CONFIDENCE_THRESHOLD   = 0.80  # min overall extraction confidence to proceed
BUDGET_COST_CAP_CENTS  = 200   # default $ cap per run cycle
RESPONSE_DEADLINE_DAYS = 14    # after which no-response → escalate
```
`# ASSUMPTION: CONFIDENCE_THRESHOLD 0.80, BUDGET_COST_CAP_CENTS $2, FOLLOWUP 4d,
RESPONSE_DEADLINE 14d are placeholder defaults pending real Dana calibration.`

### Global rules (apply in every state)

- **Kill switches (0-priority):** global env flag `ROWAN_KILL_SWITCH` halts ALL
  outbound tool actions (reads still run); per-org `organizations.agent_enabled=false`
  freezes the org; per-run `runs.status='paused'` (PM takeover) freezes one run.
  A frozen run takes no action and remains in its current state until resumed.
- **Out-of-allowlist action → `errored`.** Any attempt to invoke an action not
  in the current state's allowlist throws, writes a `guardrail_trip` event, and
  transitions to `errored`. This is enforced in code, not by convention.
- **Budget exhaustion** on any capped counter (outreach, LLM/doc, cost) blocks
  the capped action and routes to `escalate_to_pm` (never silently proceeds).

## States, transitions, guards, allowlisted actions

Legend: triggers are `scheduler` (timer tick), `webhook` (inbound email),
`human` (PM action), `tool` (tool completion callback).

### `monitoring`
- **Allowlist:** `evaluate_expiry` (read-only). No outbound actions.
- **→ renewal_due_soon** [scheduler] guard: `now >= due_date - RENEWAL_LEAD_DAYS`
  AND vendor active AND agent enabled.

### `renewal_due_soon`
- **Allowlist:** `send_email` (first outreach), `escalate_to_pm`.
- **→ first_outreach_sent** [scheduler] guard: outreach sent OK AND
  `outreach_email_count < MAX_OUTREACH` AND vendor has `primary_email` AND not
  killed/paused AND `cost_cents_spent < BUDGET_COST_CAP_CENTS`.
- **→ escalated_to_pm** [scheduler] guard: no `primary_email`
  (reason `no_contact_email`) OR budget already exhausted.

### `first_outreach_sent`
- **Allowlist:** record send, transition. (Transient book-keeping state.)
- **→ awaiting_vendor_response** [tool] guard: `send_email` returned a provider id
  (delivery accepted); `email_messages` row + `next_action_at =
  now + FOLLOWUP_INTERVAL_DAYS` written.

### `awaiting_vendor_response`  (the CLAUDE.md canonical example)
- **Allowlist — EXACTLY three:** `wait`, `follow_up_within_budget` (`send_email`),
  `escalate_to_pm`. Nothing else.
- **→ document_received** [webhook] guard: inbound email on this run's
  `reply_token` carries ≥1 attachment passing pre-LLM file guardrails (type in
  {pdf, png, jpg, tiff}, size ≤ MAX_FILE_BYTES).
- **→ awaiting_vendor_response (self, follow-up)** [scheduler] guard:
  `now >= next_action_at` AND `outreach_email_count < MAX_OUTREACH` AND
  `now < due_date + RESPONSE_DEADLINE_DAYS` AND within cost cap. Sends a
  follow-up; increments counter; resets `next_action_at`.
- **→ escalated_to_pm** [scheduler] guard: `outreach_email_count >= MAX_OUTREACH`
  OR `now >= due_date + RESPONSE_DEADLINE_DAYS` (reason `no_response`).

### `document_received`
- **Allowlist:** `classify_and_store_document` (deterministic: store +
  file-type/size + PII-redaction pre-LLM guardrails only — see Amendment
  (2026-07-18)), `escalate_to_pm`, transition→parsing.
- **→ parsing** [tool] guard: attachment stored (`coi_documents`) AND passed
  file-type/size + PII-redaction pre-LLM guardrails. Content classification
  ("is this actually a COI") is deferred to `parsing` — see below.
- **→ needs_human_review** [tool] guard: file is stored but structurally
  unreadable/corrupt at the deterministic layer (reason
  `unclassifiable_document`). This is the narrow, pre-LLM case only; the
  broader "wrong document type" judgment happens in `parsing`.

### `parsing`
- **Allowlist:** `parse_document` (LLM — two sub-passes, classify then
  extract, see Amendment (2026-07-18)), transition.
- **→ validating** [tool] guard: classify pass confirms COI type AND extract
  pass is schema-valid AND `overall_confidence >= CONFIDENCE_THRESHOLD` AND
  `llm_calls_this_doc <= MAX_LLM_PER_DOC` (budget covers both passes combined).
- **→ needs_human_review** [tool] guard: classify pass says not-a-COI /
  sub-threshold (reason `unclassifiable_document`) OR extract pass
  schema-invalid / sub-threshold confidence OR per-document LLM budget
  exhausted (reason `low_confidence_extraction`). **Never guesses a field.**

### `validating`  (deterministic — no LLM decides pass/fail)
- **Allowlist:** run deterministic validation, faithfulness check,
  draft-explanation (LLM, prose only), transition. Writes `coi_validations`.
- **→ escalated_to_pm** [tool] guard: retrieval fallback — vendor has no
  `vendor_coverage_requirements`, OR a required line has no backing KB row
  (`source_compliance_requirement_id` null / KB row inactive). Reason
  `no_requirements_on_file`. **Never validates against guessed requirements.**
- **→ filed** [tool] guard: `result='pass'` (every required line met,
  all-or-nothing) AND `faithfulness_ok=true` AND no high-severity flag.
- **→ needs_human_review** [tool] guard: `result='fail'` OR `faithfulness_ok=false`
  OR any high-severity flag (reason from `coi_validations.flags`). The LLM-drafted
  explanation is attached to the escalation but does not change the routing.

### `filed`  (consequential — gated)
- **Allowlist:** `file_document` (mark `is_current`, supersede prior),
  `mark_task_complete`, notify PM ("handled"), transition→monitoring.
- **`mark_task_complete` guard (consequential-action rule):** allowed ONLY if
  `coi_validations.result='pass' AND faithfulness_ok` OR a human `escalation`
  was resolved `approved`. **Never on LLM judgment alone.**
- **→ monitoring** [tool] guard: document filed; run reset with
  `due_date = new coi valid_to - RENEWAL_LEAD_DAYS`; counters reset for next cycle.

### `needs_human_review`  (human-gated)
- **Allowlist:** create/update `escalation(kind=needs_human_review)`, notify,
  `wait`; on human decision, transition.
- **→ filed** [human] guard: PM `approve` (overrides a fail with explicit sign-off;
  recorded as `human_intervention`). This is the human-approval path for
  consequential completion.
- **→ awaiting_vendor_response** [human] guard: PM `request_revision` → sends a
  revision-request `send_email` (if outreach budget remains — `revision_request`
  IS vendor-outreach and counts against `MAX_OUTREACH`, see Amendment
  (2026-07-18)), else escalate.
- **→ escalated_to_pm** [human] guard: PM `reject` without revision path
  (reason `rejected_by_pm`).

### `escalated_to_pm`  (human-gated)
- **Allowlist:** create `escalation(kind=escalated_to_pm)`, notify PM, `wait`;
  on resolve, transition.
- **→ monitoring** [human] guard: PM marks resolved and COI is acceptable /
  handled out-of-band.
- **→ awaiting_vendor_response** [human] guard: PM asks Rowan to keep chasing
  (re-opens outreach if budget remains).

### `errored`
- **Allowlist:** log, notify ops/PM, `wait`. No automated outbound.
- **→ (prior state)** [human] guard: explicit human recovery after the fault is
  addressed. Re-entry point recorded in `agent_events`.

## Transition summary table

| From | To | Trigger | Key guard |
|------|----|---------|-----------|
| monitoring | renewal_due_soon | scheduler | due_date − lead reached |
| renewal_due_soon | first_outreach_sent | scheduler | email sent, budget/contact OK |
| renewal_due_soon | escalated_to_pm | scheduler | no email / budget out |
| first_outreach_sent | awaiting_vendor_response | tool | send accepted |
| awaiting_vendor_response | document_received | webhook | valid attachment inbound |
| awaiting_vendor_response | awaiting_vendor_response | scheduler | follow-up within budget |
| awaiting_vendor_response | escalated_to_pm | scheduler | max outreach / deadline |
| document_received | parsing | tool | stored + file guardrails passed |
| document_received | needs_human_review | tool | corrupt/unreadable file |
| parsing | validating | tool | classified COI + schema-valid + confident |
| parsing | needs_human_review | tool | not-a-COI / low confidence / budget out |
| validating | filed | tool | pass + faithful |
| validating | needs_human_review | tool | fail / unfaithful / flag |
| validating | escalated_to_pm | tool | no requirements on file |
| filed | monitoring | tool | filed + cycle reset |
| needs_human_review | filed | human | PM approve |
| needs_human_review | awaiting_vendor_response | human | request revision |
| needs_human_review | escalated_to_pm | human | reject |
| escalated_to_pm | monitoring | human | resolved |
| escalated_to_pm | awaiting_vendor_response | human | keep chasing |
| any | errored | code | out-of-allowlist action / hard tool failure |
| errored | prior | human | recovery |
| any (active) | (frozen) | kill/pause | no transition until resumed |

## Consequences

- Every consequential outcome (`mark_task_complete`, "you're covered") is gated
  on deterministic validation OR explicit human approval — never LLM judgment.
- The action allowlist is data (per-state set), checked before every tool call;
  violations are observable (`guardrail_trip`) and fail safe (`errored`).
- Budgets are enforced at guard evaluation, so no path can overspend.
- Retrieval fallback and faithfulness are transition guards, not soft checks.

## Amendment (2026-07-18): four gaps resolved after backend build

Companion to ADR 0004's amendment (tool-contract side) and ADR 0001's
amendment (schema/RLS side) — same four items, resolved together so all
three ADRs agree.

**1. `revision_request` counts against `MAX_OUTREACH` — ADR 0002 is
authoritative over ADR 0004's old assumption text.** This ADR's
`needs_human_review → awaiting_vendor_response` transition already gated
`request_revision` on "(if outreach budget remains), else escalate" — that
was always the intended behavior; ADR 0004's tool-contract assumption (which
grouped `revision_request` with budget-exempt PM notices) was the stale one
and has been corrected there. Reasoning: `revision_request` is a message to
the *vendor* asking for a corrected document — it is vendor outreach by
definition, however it was triggered (PM-initiated vs. scheduler-initiated
makes no difference to the vendor's inbox or to the 3-email courtesy cap
CLAUDE.md sets). Budget-exempt notices are only the ones that never leave
the PM's inbox (`handled_notice`, `escalation_notice`).

**2. No new `classify_document` tool; classification folded into
`parsing`.** The `document_received` and `parsing` state definitions above
are rewritten to reflect this: `document_received → parsing` is now guarded
by deterministic storage/file-guardrail checks only (unconditional once
those pass), and the actual "is this a COI" judgment — previously described
vaguely as "classifier says COI" at the `document_received` boundary — now
explicitly happens as the first LLM sub-pass inside `parsing`, gating
`parsing → validating` / `parsing → needs_human_review` alongside the
extraction pass. This keeps the tool count at six (per CLAUDE.md's tool
list) and keeps classification as a prompt/eval concern owned by
agent-engineer rather than a new side-effecting capability. See ADR 0004's
amendment for the `parse_document` contract change (two sub-passes, one
shared per-document LLM budget) and `backend/README.md`'s note that
agent-engineer should extend `ExtractionEngine` (`app/tools/parse_document.py`)
rather than build a new Protocol.
`# ASSUMPTION: v1 may ship with backend-engineer's deterministic stopgap
(any file passing type/size guardrails is treated as a COI candidate, with
low extraction confidence catching non-COI documents downstream) until
agent-engineer wires the real classify pass. This is an acceptable interim
state — it still never guesses and still routes doubt to human review — not
a design deviation.`

**3. `llm_calls_this_doc` resets on new document; `cost_cents_spent` does
NOT.** `MAX_LLM_PER_DOC` is, as named, a per-document cap — `runs.llm_call_count`
correctly resets to 0 whenever a new `coi_document_id` enters `parsing`
(covers both the classify and extract sub-passes together). `BUDGET_COST_CAP_CENTS`
is a **per-run-cycle** cap per CLAUDE.md ("max configurable $ per run") and
must accumulate across every document/re-parse within one run cycle, not
reset per document — otherwise repeated PM-requested revisions could drive
cumulative spend past the configured cap in unbounded increments. backend-
engineer's current code resets both counters together in
`advance_from_document_received`; per ADR 0004's amendment this is a one-line
bug to fix (stop resetting `cost_cents_spent`), not an ADR disagreement.

**4. `rowan_system`'s extended grant — see ADR 0001 Amendment.** No
state-machine change; the webhook resolving `reply_token → run →
organization_id` before the runner is invoked is a pre-orchestration
concern.
