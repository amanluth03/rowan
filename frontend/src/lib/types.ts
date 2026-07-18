/**
 * Shared enums + read-model DTO shapes for the Rowan frontend.
 *
 * These mirror ADR 0001 (Postgres schema / enums) and the boundary contracts
 * in ADR 0003 ("Orchestration -> Interface: read-model DTOs -- RunTraceDTO,
 * ActivityFeedItemDTO, VendorStatusDTO, ReviewQueueItemDTO ... carry evidence
 * refs (document url, parsed values, source_citation). No DB rows leak; no
 * internal enums the UI shouldn't see.").
 *
 * RECONCILED (2026-07-18) against the real backend (`backend/app/api/schemas.py`,
 * committed at `61061a1`) -- this file was originally written before that
 * schema existed (flagged then as a proposal, not a ratified contract; see
 * backend/README.md's "DTO shape notes for frontend-engineer"). Four real
 * mismatches were found and fixed here rather than papered over with a cast:
 *
 * 1. `LineComparisonDTO.severity` / `FlagDTO.severity` -- narrowed from
 *    `EventSeverity` to `ComparisonSeverity` (`"info" | "error"`, `"warn"`
 *    never appears on these two fields; see `_dto_severity` in
 *    `backend/app/api/read_models.py`).
 * 2. `VendorStatusDTO.activeRun.dueDate` / `RunTraceDTO.dueDate` -- widened
 *    to `string | null` (`runs.due_date` has no NOT NULL constraint; a
 *    freshly onboarded vendor with no known current-COI expiry has
 *    `due_date=NULL` until a document is filed or a PM sets one).
 * 3. `VendorStatusDTO.primaryPropertyName` / `primaryPropertyJurisdiction` --
 *    widened to `string | null` (`vendors.primary_property_id` is nullable).
 * 4. `currentCoi.filedAt` -- kept as a non-null `string` (the real DTO's
 *    `filed_at` is always present when `currentCoi` exists), but see the
 *    comment on that field: it's approximated as `coi_documents.received_at`
 *    server-side, not a real "the moment this was filed" timestamp -- there
 *    is no separate `filed_at` column (ADR 0001).
 */

// ---------------------------------------------------------------------------
// Enums (ADR 0001)
// ---------------------------------------------------------------------------

export type CoverageType =
  | "general_liability"
  | "auto_liability"
  | "workers_comp"
  | "umbrella_excess"
  | "professional_liability"
  | "pollution"
  | "employers_liability";

export type VendorRole =
  | "plumber"
  | "electrician"
  | "hvac"
  | "general_contractor"
  | "landscaper"
  | "roofer"
  | "cleaner"
  | "pest_control"
  | "other";

export type PropertyType =
  | "single_family"
  | "multi_family"
  | "condo"
  | "commercial"
  | "mixed_use";

export type RunState =
  | "monitoring"
  | "renewal_due_soon"
  | "first_outreach_sent"
  | "awaiting_vendor_response"
  | "document_received"
  | "parsing"
  | "validating"
  | "filed"
  | "needs_human_review"
  | "escalated_to_pm"
  | "errored";

export type RunStatus = "active" | "paused" | "completed" | "errored";

export type EventType =
  | "state_transition"
  | "tool_call"
  | "llm_call"
  | "guardrail_trip"
  | "human_intervention"
  | "error"
  | "note";

export type EventSeverity = "info" | "warn" | "error";

/** Coarser vocabulary used only by `LineComparisonDTO.severity` and
 * `FlagDTO.severity` -- see the reconciliation note at the top of this file. */
export type ComparisonSeverity = "info" | "error";

export type DocStatus =
  | "received"
  | "parsing"
  | "parsed"
  | "filed"
  | "rejected"
  | "superseded";

export type DocSource = "email_inbound" | "manual_upload" | "onboarding_import";

export type EmailDirection = "outbound" | "inbound";

export type EscalationKind = "needs_human_review" | "escalated_to_pm";

export type EscalationStatus = "open" | "acknowledged" | "resolved";

export type ValidationResult = "pass" | "fail";

// Derived, UI-facing compliance status for a vendor -- a rollup, not a DB enum.
export type ComplianceStatus =
  | "compliant"
  | "expiring_soon"
  | "needs_review"
  | "escalated"
  | "no_requirements"
  | "pending";

// ---------------------------------------------------------------------------
// Shared evidence primitives
// ---------------------------------------------------------------------------

/** A pointer back to the source document backing a rendered claim. */
export interface DocumentRef {
  documentId: string;
  url: string;
  filename: string;
  contentType: string;
  versionNumber: number;
}

/** One required coverage line, always traceable to a cited KB row. */
export interface RequirementLineDTO {
  vendorCoverageRequirementId: string;
  coverageType: CoverageType;
  minEachOccurrence: number | null; // whole dollars
  minAggregate: number | null; // whole dollars
  requiresAdditionalInsured: boolean;
  requiresWaiverOfSubrogation: boolean;
  requiresPrimaryNoncontributory: boolean;
  /** null => PM-entered override with no KB backing (flagged as unverified). */
  sourceComplianceRequirementId: string | null;
  sourceCitation: string | null;
  sourceUrl: string | null;
  lastVerifiedAt: string | null; // ISO
  confirmedByPm: boolean;
}

/** What the extraction pass read off the document for one coverage line. */
export interface ParsedLineDTO {
  coverageType: CoverageType;
  eachOccurrence: number | null;
  aggregate: number | null;
  additionalInsured: boolean | null;
  waiverOfSubrogation: boolean | null;
  primaryNoncontributory: boolean | null;
  confidence: number | null; // 0..1
}

/** Required vs. parsed, pass/fail, for one coverage line -- the review-queue unit. */
export interface LineComparisonDTO {
  coverageType: CoverageType;
  required: RequirementLineDTO;
  parsed: ParsedLineDTO | null;
  pass: boolean;
  severity: ComparisonSeverity;
  note: string | null;
}

export interface FlagDTO {
  code: string;
  message: string;
  severity: ComparisonSeverity;
}

// ---------------------------------------------------------------------------
// ActivityFeedItemDTO -- home / hero surface
// ---------------------------------------------------------------------------

export type ActivityFeedItemKind =
  | "run_filed"
  | "outreach_sent"
  | "follow_up_sent"
  | "document_received"
  | "validation_failed"
  | "needs_human_review"
  | "escalated_to_pm"
  | "human_resolved"
  | "renewal_due_soon";

export interface ActivityFeedItemDTO {
  id: string;
  runId: string;
  vendorId: string;
  vendorName: string;
  vendorRole: VendorRole;
  kind: ActivityFeedItemKind;
  /** Rendered verbatim as the work-log headline, e.g. "Renewed COI for Hernandez Plumbing -- valid through 3/2027 -- filed." */
  headline: string;
  detail: string | null;
  state: RunState;
  severity: EventSeverity;
  occurredAt: string; // ISO
  actionRequired: boolean;
  evidence: {
    document: DocumentRef | null;
    validTo: string | null; // ISO date
    sourceCitation: string | null;
  };
}

// ---------------------------------------------------------------------------
// VendorStatusDTO -- vendor list + detail
// ---------------------------------------------------------------------------

export interface CoiHistoryItemDTO {
  document: DocumentRef;
  status: DocStatus;
  validFrom: string | null;
  validTo: string | null;
  isCurrent: boolean;
  receivedAt: string;
  source: DocSource;
}

export interface VendorStatusDTO {
  id: string;
  organizationId: string;
  name: string;
  role: VendorRole;
  primaryEmail: string | null;
  status: "active" | "inactive";
  /** Nullable: `vendors.primary_property_id` is nullable (real schema). */
  primaryPropertyName: string | null;
  /** Nullable, "City, ST" when present. */
  primaryPropertyJurisdiction: string | null;
  complianceStatus: ComplianceStatus;
  currentCoi: {
    document: DocumentRef;
    validFrom: string;
    validTo: string;
    /** Approximated as `coi_documents.received_at` -- there is no real
     * `filed_at` column (ADR 0001); not the moment `file_document` flipped
     * `is_current`. See backend/README.md's DTO shape notes. */
    filedAt: string;
  } | null;
  requirements: RequirementLineDTO[];
  activeRun: {
    runId: string;
    state: RunState;
    status: RunStatus;
    /** Nullable: `runs.due_date` has no NOT NULL constraint -- a freshly
     * onboarded vendor with no known current-COI expiry has `due_date=NULL`
     * until a document is filed or a PM sets one. */
    dueDate: string | null;
    nextActionAt: string | null;
    outreachEmailCount: number;
    maxOutreach: number;
  } | null;
  history: CoiHistoryItemDTO[];
}

// ---------------------------------------------------------------------------
// RunTraceDTO -- run detail / trace timeline
// ---------------------------------------------------------------------------

export interface AgentEventDTO {
  id: string;
  type: EventType;
  name: string; // OTel-compatible span name, e.g. "tool.send_email"
  severity: EventSeverity;
  fromState: RunState | null;
  toState: RunState | null;
  toolName: string | null;
  llmModel: string | null;
  promptHash: string | null;
  inputTokens: number | null;
  outputTokens: number | null;
  costCents: number | null;
  latencyMs: number | null;
  payload: Record<string, unknown>;
  createdAt: string; // ISO
}

export interface RunTraceDTO {
  runId: string;
  vendorId: string;
  vendorName: string;
  vendorRole: VendorRole;
  state: RunState;
  status: RunStatus;
  trigger: "renewal_due" | "manual";
  /** Nullable, same reason as `VendorStatusDTO.activeRun.dueDate` above. */
  dueDate: string | null;
  startedAt: string;
  updatedAt: string;
  completedAt: string | null;
  budget: {
    outreachEmailCount: number;
    maxOutreach: number;
    llmCallCount: number;
    maxLlmCallsPerDoc: number;
    costCentsSpent: number;
    budgetCostCapCents: number;
  };
  events: AgentEventDTO[];
}

// ---------------------------------------------------------------------------
// ReviewQueueItemDTO -- human review queue
// ---------------------------------------------------------------------------

export interface ReviewQueueItemDTO {
  escalationId: string;
  runId: string;
  vendorId: string;
  vendorName: string;
  vendorRole: VendorRole;
  kind: EscalationKind;
  reasonCode: string;
  severity: EventSeverity;
  summary: string;
  status: EscalationStatus;
  createdAt: string;
  document: DocumentRef | null;
  comparison: LineComparisonDTO[];
  flags: FlagDTO[];
  faithfulnessOk: boolean;
  overallConfidence: number | null;
}
