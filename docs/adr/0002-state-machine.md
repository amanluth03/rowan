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
- **Allowlist:** classify+store document, `escalate_to_pm`, transition→parsing.
- **→ parsing** [tool] guard: attachment stored (`coi_documents`), passed
  file-type/size + PII-redaction pre-LLM guardrails, and classifier says "COI".
- **→ needs_human_review** [tool] guard: classifier says not-a-COI / unreadable
  (reason `unclassifiable_document`).

### `parsing`
- **Allowlist:** `parse_document` (LLM extraction), transition.
- **→ validating** [tool] guard: extraction schema-valid AND
  `overall_confidence >= CONFIDENCE_THRESHOLD` AND
  `llm_call_count(this doc) <= MAX_LLM_PER_DOC`.
- **→ needs_human_review** [tool] guard: schema-invalid OR sub-threshold
  confidence OR extraction budget exhausted (reason `low_confidence_extraction`).
  **Never guesses a field.**

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
  revision-request `send_email` (if outreach budget remains), else escalate.
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
| document_received | parsing | tool | stored + classified COI |
| document_received | needs_human_review | tool | unclassifiable |
| parsing | validating | tool | schema-valid + confident |
| parsing | needs_human_review | tool | low confidence / budget out |
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
