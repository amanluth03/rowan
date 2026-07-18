# ADR 0003 — Six-layer model and boundary contracts

**Status:** Proposed
**Layer:** all (this ADR defines the seams)
**Depends on:** 0001, 0002, 0004, 0005.

## Decision

The system is six layers with one-directional dependencies and typed contracts
at every seam. **No module reaches across a non-adjacent layer; no single prompt
template spans layers; the LLM never touches the DB or email provider — only the
tool layer does.** The architect rejects any PR that violates this.

```
┌──────────────────────────────────────────────────────────────┐
│ 1. INTERFACE        Next.js UI + FastAPI API routes           │
│    (Vercel)         renders feed / vendor / run-trace / queue │
└───────────────▲──────────────────────────┬───────────────────┘
                │ DTOs (read models)        │ commands (typed)
┌───────────────┴──────────────────────────▼───────────────────┐
│ 2. ORCHESTRATION    deterministic persisted state machine     │
│    (0002)           picks next action from per-state allowlist│
└───┬───────────────┬───────────────────┬──────────────────┬───┘
    │ tool call      │ retrieval query   │ policy check     │ event
┌───▼──────────┐ ┌───▼─────────────┐ ┌───▼──────────┐ ┌────▼────────┐
│ 3. TOOLS     │ │ 4. RETRIEVAL/   │ │ 5. POLICY/   │ │ 6. OBSERV./ │
│ send_email   │ │    MEMORY       │ │    SAFETY    │ │    EVALS    │
│ parse_document│ │ run state (a)  │ │ allowlists   │ │ agent_events│
│ update_coi   │ │ entity (b)      │ │ guardrails   │ │ trace       │
│ file_document│ │ requirements(c) │ │ kill switches│ │ eval harness│
│ escalate_pm  │ │ (0005)          │ │ budgets      │ │ (0001)      │
│ mark_complete│ └───┬─────────────┘ └──────────────┘ └─────────────┘
│ (0004)       │     │ SQL (RLS-scoped)
└───┬──────────┘     ▼
    │ side effects  Postgres / Supabase Storage
    ▼
  Resend (send-only) · Claude API · Storage
```

### What lives where

- **1 Interface** — Next.js pages (feed, vendor list/detail, run trace, review
  queue, onboarding) and FastAPI HTTP routes. Renders read models; issues typed
  commands. Contains no business rules, no state transitions, no prompts.
- **2 Orchestration** — the state machine (0002). The ONLY place transitions
  happen. Selects the next allowlisted action; calls tools, retrieval, policy;
  emits events. Holds no SQL of its own beyond run-state writes routed through
  the retrieval layer's repositories. Contains no prompt text and no provider SDK
  calls.
- **3 Tools** — the only layer that performs side effects (DB writes to entity
  tables, Resend sends, Claude API calls, Storage writes). Each tool is a typed,
  schema-validated function (0004). Prompts live here, scoped to a single tool
  (extraction prompt inside `parse_document`; explanation prompt inside the
  drafting tool) — never a monolithic cross-layer prompt.
- **4 Retrieval/memory** — repositories over Postgres for the three tiers (0005).
  Deterministic reads; enforces RLS scoping. Owns the `RequirementsRetriever`
  interface. Returns typed rows, never raw SQL or ORM objects, upward.
- **5 Policy/safety** — pure functions + config: per-state action allowlist,
  pre/post-LLM guardrails, budget checks, kill-switch reads. No I/O side effects
  of its own (except reading config/flags); returns allow/deny + reason.
- **6 Observability/evals** — the `agent_events` writer, trace assembly, daily
  rollups, and the CI eval harness (`tests/evals/`). Write-mostly + read for
  trace render. Never influences control flow (observing, not deciding).

### Boundary contracts (what crosses, in what shape)

- **Interface → Orchestration:** typed **commands** only —
  `StartRun`, `PauseRun`, `ResumeRun`, `ApproveReview`, `RejectReview`,
  `RequestRevision`, `ResolveEscalation`, `AddVendor`, `SetRequirements`.
  Never raw SQL, never a tool call, never a prompt. Validated (Pydantic) at the
  API edge.
- **Orchestration → Interface:** **read-model DTOs** — `RunTraceDTO`,
  `ActivityFeedItemDTO`, `VendorStatusDTO`, `ReviewQueueItemDTO`. Assembled from
  retrieval + observability; carry evidence refs (document url, parsed values,
  `source_citation`). No DB rows leak; no internal enums the UI shouldn't see.
- **Orchestration → Tools:** a validated **tool input struct** + the run context
  (`run_id`, `organization_id`, budget snapshot, idempotency key). Tool returns a
  validated **tool output struct** (0004). Orchestration never sees the provider
  SDK.
- **Orchestration → Retrieval:** a **query struct** (e.g. `RequirementsQuery`,
  `VendorHistoryQuery`); gets back typed rows. Orchestration passes no SQL.
- **Orchestration/Tools → Policy:** `(state, proposed_action, run_context)` →
  `PolicyDecision{allow, reason, guardrail_name}`. Callers MUST honor a deny.
- **All layers → Observability:** append-only `AgentEvent` structs. One-way.
  Observability returns nothing that changes control flow.
- **Tools → external:** Resend (send-only credential), Claude API, Storage,
  Postgres via RLS-scoped role. This is the ONLY layer with external clients.

### Hard "must NOT couple" rules (rejection criteria in review)

1. LLM output must not be executed as a DB write or an email send directly — it
   is data returned to a tool, which validates then acts.
2. No prompt template may contain retrieval SQL, tool-dispatch logic, or state
   transitions. One prompt = one bounded task inside one tool.
3. The Interface layer may not call Tools or Retrieval directly — only
   Orchestration, via commands. (Read-only DTO assembly may query retrieval, but
   through a read-model service, not ad-hoc SQL in a route.)
4. Policy decisions may not depend on LLM judgment for consequential actions
   (0002 `mark_task_complete` rule).
5. Observability may not be a dependency of any control-flow decision.
6. The state machine, not the LLM, owns "what happens next." The LLM only fills
   bounded slots (extraction, explanation prose).

## Consequences

- Layers are independently buildable and testable: backend-engineer owns 3/4,
  agent-engineer owns 2 + the prompts in 3, frontend-engineer owns 1,
  security-reviewer audits 5 across all, qa-evals owns 6.
- Swapping Resend, the Claude model, or (v2) the requirements retriever touches
  exactly one layer.
- `# ASSUMPTION: FastAPI hosts layers 2–6 as one deployable in v1 (a modular
  monolith with enforced internal module boundaries), not separate services —
  simplest thing that preserves the seams. Splitting to services is a v2 option.`
