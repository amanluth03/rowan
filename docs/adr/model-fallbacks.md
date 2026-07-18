# Model fallback log

Tracks every model change to `.claude/agents/*.md`, per CLAUDE.md's model fallback policy. Planned downgrades are logged for traceability even though only reactive downgrades are required to be logged.

| Timestamp | Agent | Change | Type | Reason |
|---|---|---|---|---|
| 2026-07-18 | architect | opus → sonnet | planned | ADRs (0001–0005) approved by human; Step 2 build begins. Architect's judgment-heavy work was front-loaded in design; remaining arbitration doesn't need Opus, per CLAUDE.md's planned-default policy. |
