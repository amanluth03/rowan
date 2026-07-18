/**
 * Shared enums + read-model DTO shapes for the Rowan frontend.
 *
 * These mirror ADR 0001 (Postgres schema / enums) and the boundary contracts
 * in ADR 0003 ("Orchestration -> Interface: read-model DTOs -- RunTraceDTO,
 * ActivityFeedItemDTO, VendorStatusDTO, ReviewQueueItemDTO ... carry evidence
 * refs (document url, parsed values, source_citation). No DB rows leak; no
 * internal enums the UI shouldn't see.").
 *
 * # ASSUMPTION: ADR 0003 names the four DTOs and says they carry evidence
 * refs, but does not give exact field lists. The concrete shapes below are a
 * frontend-engineer design choice, built to make every rendered claim
 * traceable to evidence (document url / parsed value / source_citation) per
 * CLAUDE.md's brand section. Backend-engineer / architect should treat this
 * file as the frontend's proposal for the wire shape, not a ratified contract.
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
  severity: EventSeverity;
  note: string | null;
}

export interface FlagDTO {
  code: string;
  message: string;
  severity: EventSeverity;
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
  primaryPropertyName: string;
  primaryPropertyJurisdiction: string; // "City, ST"
  complianceStatus: ComplianceStatus;
  currentCoi: {
    document: DocumentRef;
    validFrom: string;
    validTo: string;
    filedAt: string;
  } | null;
  requirements: RequirementLineDTO[];
  activeRun: {
    runId: string;
    state: RunState;
    status: RunStatus;
    dueDate: string;
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
  dueDate: string;
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
