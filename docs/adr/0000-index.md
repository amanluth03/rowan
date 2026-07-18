# ADR Index — Rowan Vendor COI Renewal Agent (v1)

These ADRs are the buildable design that backend-engineer, agent-engineer,
frontend-engineer, security-reviewer, and qa-evals-engineer build against.
They turn `CLAUDE.md` into concrete contracts. Where an ADR and `CLAUDE.md`
disagree, `CLAUDE.md` wins — file an issue, do not silently diverge.

| ADR | Title | Owns |
|-----|-------|------|
| [0001](0001-postgres-schema.md) | Postgres schema + migration plan | tables, relations, RLS, indexes |
| [0002](0002-state-machine.md) | Renewal state machine spec | states, transitions, guards, per-state action allowlists |
| [0003](0003-six-layer-model-and-boundaries.md) | Six-layer model + boundary contracts | what lives where, what crosses each seam |
| [0004](0004-tool-contracts.md) | Tool contracts | I/O schemas, idempotency, budgets, timeouts, failure modes |
| [0005](0005-requirements-retriever.md) | RequirementsRetriever interface | v1 deterministic predicate, v2 seam, fallback, faithfulness |

## Status

Proposed. Awaiting human approval via the tech-lead session before Step 2
(code) begins. No application code is written until these are approved.

## Cross-cutting conventions (binding on all ADRs)

- **Tenant scoping:** every tenant-owned row carries `organization_id`. RLS
  scopes every read/write to the caller's org (0001).
- **Time:** all timestamps are `timestamptz`, stored UTC. Column suffix `_at`.
- **IDs:** UUID v7 (time-sortable) primary keys, generated app-side, column
  `id`. Foreign keys named `<entity>_id`.
- **Money:** integer cents + ISO-4217 `currency`, never floats. Coverage limits
  stored as integer dollars (COI limits are whole-dollar).
- **Enums:** Postgres native `enum` types for closed sets (states, severities).
- **No layer coupling:** the LLM never touches the DB or email provider; it is
  reached only through the tool layer (0003, 0004). No single prompt template
  spans layers.

## Open questions requiring human input

Collected inline as `# ASSUMPTION:` markers throughout. See each ADR's
"Assumptions" section and the consolidated list in the architect's report.
