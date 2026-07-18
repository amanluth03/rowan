# ADR 0005 — RequirementsRetriever interface (v1 deterministic, v2 seam)

**Status:** Proposed
**Layer:** Retrieval/memory, tier (c). Consumed by Orchestration (0002) via a
query struct; never called by the LLM directly.
**Depends on:** 0001 (`compliance_requirements`, `vendor_coverage_requirements`).

## Decision

Requirements retrieval is a **deterministic structured-predicate lookup** over a
human-curated `compliance_requirements` table — not semantic search. Per
CLAUDE.md, deterministic predicate retrieval is the correct implementation for
structured, curated compliance knowledge; semantic search adds failure modes
without adding recall. A clean `RequirementsRetriever` interface isolates this
so a v2 semantic-RAG curation workflow can slot in without touching the agent.

`# ASSUMPTION: semantic RAG deferred until the curation workflow exists; v1
knowledge is human-curated rows with source_citation + last_verified_at.`

### Interface (the seam)

```python
class RequirementsQuery(BaseModel):
    organization_id: UUID
    jurisdiction_state: str
    jurisdiction_city: str | None
    jurisdiction_hoa: str | None
    property_type: PropertyType | None
    vendor_role: VendorRole

class RetrievedRequirement(BaseModel):
    id: UUID                       # compliance_requirements.id — the faithfulness anchor
    coverage_type: CoverageType
    min_each_occurrence: int | None
    min_aggregate: int | None
    requires_additional_insured: bool
    requires_waiver_of_subrogation: bool
    requires_primary_noncontributory: bool
    source_citation: str           # NOT NULL by construction
    source_url: str | None
    last_verified_at: datetime      # NOT NULL by construction

class RetrievalResult(BaseModel):
    requirements: list[RetrievedRequirement]
    found: bool                    # False → fallback fires (never []→proceed)
    query: RequirementsQuery

class RequirementsRetriever(Protocol):
    def retrieve(self, q: RequirementsQuery) -> RetrievalResult: ...
```

Orchestration depends only on this Protocol. `V1DeterministicRetriever` and a
future `V2SemanticRetriever` are interchangeable implementations; swapping them
touches DI wiring only — no agent, state-machine, or tool code changes.

### v1 implementation — `V1DeterministicRetriever`

Predicate match with jurisdiction specificity ranking (most-specific wins,
`NULL` in a KB column = "applies to any"):

```sql
SELECT * FROM compliance_requirements
WHERE organization_id = :org AND active
  AND jurisdiction_state = :state
  AND (jurisdiction_city IS NULL OR jurisdiction_city = :city)
  AND (jurisdiction_hoa  IS NULL OR jurisdiction_hoa  = :hoa)
  AND (property_type     IS NULL OR property_type     = :ptype)
  AND (vendor_role       IS NULL OR vendor_role       = :role)
ORDER BY coverage_type,
  -- specificity: prefer city/hoa/type/role-specific rows over "any"
  (jurisdiction_city IS NOT NULL)::int + (jurisdiction_hoa IS NOT NULL)::int
  + (property_type IS NOT NULL)::int + (vendor_role IS NOT NULL)::int DESC;
```

Then reduce to **one row per `coverage_type`** (the most specific), yielding the
applicable requirement set. Backed by the tier-c index in 0001.

**Context resolution (locked "one set per vendor, org-wide"):** a vendor gets a
single requirement set. The query's jurisdiction/property attributes come from
`vendors.primary_property_id` (its resolving context). At onboarding the result
materializes into `vendor_coverage_requirements` (one row per coverage_type),
each carrying `source_compliance_requirement_id = RetrievedRequirement.id`.
`# ASSUMPTION: multi-jurisdiction vendors resolve to their primary property's
context in v1; per-property requirement variation is a v2 concern (consistent
with the locked one-set-per-vendor decision).`

### Retrieval fallback (required)

If `retrieve()` returns `found=False` (no KB row for the jurisdiction/property
combination), the agent **never guesses or applies defaults**. The machine:
1. writes a `guardrail_trip` event `no_requirements_on_file`,
2. transitions `validating → escalated_to_pm` (0002),
3. surfaces "No verified requirements on file for {state}/{city}/{role}" to the
   PM with the exact query that missed, so curation can fill the gap.

This also fires at validation time if a `vendor_coverage_requirements` line has a
null or inactive `source_compliance_requirement_id`.

### Faithfulness check (required, structural — IDs in, IDs out)

Enforced by construction, not trust:
1. **IDs in:** every `vendor_coverage_requirements` line used in validation
   carries a `source_compliance_requirement_id` that resolved from a
   `RetrievedRequirement.id`.
2. **IDs out:** every asserted line in the `coi_validations.line_results` output
   MUST reference both `vendor_coverage_requirement_id` and its
   `source_compliance_requirement_id`. Validation code asserts the set of
   source IDs in the output ⊆ the set of retrieved IDs.
3. Any asserted requirement lacking a backing retrieved ID → `faithfulness_ok =
   false` → route to `needs_human_review` (0002/0004), regardless of pass/fail.

Because the requirement set is deterministic rows (not LLM-generated), the LLM
literally cannot introduce a requirement that isn't in the table — the
extraction LLM reports what the COI *says*; the requirements come only from the
retriever. Faithfulness is thus a structural invariant, checked in code.

### v2 seam (no agent changes)

`V2SemanticRetriever` implements the same Protocol: it may use embeddings/RAG
over curated source documents to *propose* `RetrievedRequirement` rows, but MUST
still return real `compliance_requirements.id`s (a curation step persists any new
row first, so `source_citation`/`last_verified_at`/`id` remain non-null and the
faithfulness invariant holds unchanged). The agent, state machine, and tools are
identical across v1/v2. `# ASSUMPTION: v2 semantic retrieval still resolves to
persisted, cited KB rows — it never returns un-curated free-text requirements.`

## Consequences

- Retrieval is fast, explainable, and auditable (every requirement traces to a
  cited row with a verification date).
- Fallback and faithfulness are hard invariants enforced structurally, satisfying
  the CLAUDE.md guardrails, and are directly testable in the eval harness
  (correct-set, empty-fallback, no-unbacked-assertion checks).
- Upgrading to semantic retrieval later is a single-implementation swap behind
  the Protocol — the "seam" is the Protocol + the persist-before-cite rule.
