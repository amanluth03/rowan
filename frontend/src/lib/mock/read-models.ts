/**
 * Read-model assembly -- the mock stand-in for the "Orchestration -> Interface"
 * seam in ADR 0003. Real implementation: a FastAPI read-model service joins
 * repository rows into these same DTOs; this module does the same joins over
 * the in-memory fixtures. Every exported function is `async` and here to make
 * the eventual swap to `fetch("/api/...")` a body-only change -- call sites
 * never change shape.
 */

import type {
  ActivityFeedItemDTO,
  ActivityFeedItemKind,
  AgentEventDTO,
  ComplianceStatus,
  CoiHistoryItemDTO,
  DocumentRef,
  LineComparisonDTO,
  ParsedLineDTO,
  RequirementLineDTO,
  ReviewQueueItemDTO,
  RunTraceDTO,
  VendorStatusDTO,
} from "../types";
import {
  agentEvents,
  coiDocuments,
  coiExtractions,
  coiValidations,
  complianceRequirements,
  escalations,
  organization,
  properties,
  runs,
  vendorCoverageRequirements,
  vendors,
  type CoiDocumentRecord,
  type RunRecord,
  type VendorRecord,
} from "./fixtures";

// Simulated network latency so loading states are honest in the demo.
const LATENCY_MS = 120;
function settle<T>(value: T): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), LATENCY_MS));
}

function toDocumentRef(doc: CoiDocumentRecord): DocumentRef {
  return {
    documentId: doc.id,
    url: doc.storagePath,
    filename: doc.originalFilename,
    contentType: doc.contentType,
    versionNumber: doc.versionNumber,
  };
}

function propertyLabel(propertyId: string | null): { name: string; jurisdiction: string } {
  const p = properties.find((x) => x.id === propertyId);
  if (!p) return { name: "Unknown property", jurisdiction: "—" };
  const jurisdiction = p.hoaName ? `${p.city}, ${p.state} · ${p.hoaName}` : `${p.city}, ${p.state}`;
  return { name: p.name, jurisdiction };
}

function requirementLines(vendorId: string): RequirementLineDTO[] {
  return vendorCoverageRequirements
    .filter((r) => r.vendorId === vendorId)
    .map((r) => {
      const cr = r.sourceComplianceRequirementId
        ? complianceRequirements.find((c) => c.id === r.sourceComplianceRequirementId) ?? null
        : null;
      return {
        vendorCoverageRequirementId: r.id,
        coverageType: r.coverageType,
        minEachOccurrence: r.minEachOccurrence,
        minAggregate: r.minAggregate,
        requiresAdditionalInsured: r.requiresAdditionalInsured,
        requiresWaiverOfSubrogation: r.requiresWaiverOfSubrogation,
        requiresPrimaryNoncontributory: r.requiresPrimaryNoncontributory,
        sourceComplianceRequirementId: r.sourceComplianceRequirementId,
        sourceCitation: cr?.sourceCitation ?? null,
        sourceUrl: cr?.sourceUrl ?? null,
        lastVerifiedAt: cr?.lastVerifiedAt ?? null,
        confirmedByPm: r.confirmedByPm,
      };
    });
}

function currentDocFor(vendorId: string): CoiDocumentRecord | null {
  return coiDocuments.find((d) => d.vendorId === vendorId && d.isCurrent) ?? null;
}

function activeRunFor(vendorId: string): RunRecord | null {
  const candidates = runs
    .filter((r) => r.vendorId === vendorId && r.status !== "completed")
    .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
  return candidates[0] ?? null;
}

function complianceStatusFor(vendor: VendorRecord, run: RunRecord | null, currentDoc: CoiDocumentRecord | null): ComplianceStatus {
  const hasUnbackedRequirement = vendorCoverageRequirements.some(
    (r) => r.vendorId === vendor.id && r.sourceComplianceRequirementId === null,
  );
  if (run) {
    if (run.state === "needs_human_review") return "needs_review";
    if (run.state === "escalated_to_pm" || run.state === "errored") {
      return hasUnbackedRequirement ? "no_requirements" : "escalated";
    }
    if (["renewal_due_soon", "first_outreach_sent", "awaiting_vendor_response"].includes(run.state)) {
      return "expiring_soon";
    }
    if (["document_received", "parsing", "validating"].includes(run.state)) {
      return "pending";
    }
  }
  if (currentDoc?.validTo) {
    const daysLeft = Math.ceil((new Date(currentDoc.validTo).getTime() - Date.now()) / 86_400_000);
    if (daysLeft <= 30) return "expiring_soon";
  }
  return currentDoc ? "compliant" : "pending";
}

// ---------------------------------------------------------------------------
// VendorStatusDTO
// ---------------------------------------------------------------------------

function buildVendorStatus(vendor: VendorRecord): VendorStatusDTO {
  const currentDocRecord = currentDocFor(vendor.id);
  const run = activeRunFor(vendor.id);
  const { name: primaryPropertyName, jurisdiction } = propertyLabel(vendor.primaryPropertyId);
  const history: CoiHistoryItemDTO[] = coiDocuments
    .filter((d) => d.vendorId === vendor.id)
    .sort((a, b) => b.versionNumber - a.versionNumber)
    .map((d) => ({
      document: toDocumentRef(d),
      status: d.status,
      validFrom: d.validFrom,
      validTo: d.validTo,
      isCurrent: d.isCurrent,
      receivedAt: d.receivedAt,
      source: d.source,
    }));

  return {
    id: vendor.id,
    organizationId: vendor.organizationId,
    name: vendor.name,
    role: vendor.vendorRole,
    primaryEmail: vendor.primaryEmail,
    status: vendor.status,
    primaryPropertyName,
    primaryPropertyJurisdiction: jurisdiction,
    complianceStatus: complianceStatusFor(vendor, run, currentDocRecord),
    currentCoi: currentDocRecord && currentDocRecord.validFrom && currentDocRecord.validTo
      ? {
          document: toDocumentRef(currentDocRecord),
          validFrom: currentDocRecord.validFrom,
          validTo: currentDocRecord.validTo,
          filedAt: currentDocRecord.receivedAt,
        }
      : null,
    requirements: requirementLines(vendor.id),
    activeRun: run
      ? {
          runId: run.id,
          state: run.state,
          status: run.status,
          dueDate: run.dueDate,
          nextActionAt: run.nextActionAt,
          outreachEmailCount: run.outreachEmailCount,
          maxOutreach: organization.settings.maxOutreach,
        }
      : null,
    history,
  };
}

export async function getVendorList(): Promise<VendorStatusDTO[]> {
  return settle(vendors.map(buildVendorStatus).sort((a, b) => a.name.localeCompare(b.name)));
}

export async function getVendorStatus(vendorId: string): Promise<VendorStatusDTO | null> {
  const vendor = vendors.find((v) => v.id === vendorId);
  return settle(vendor ? buildVendorStatus(vendor) : null);
}

// ---------------------------------------------------------------------------
// RunTraceDTO
// ---------------------------------------------------------------------------

function toEventDTO(id: string): AgentEventDTO[] {
  return agentEvents
    .filter((e) => e.runId === id)
    .sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime())
    .map((e) => ({
      id: e.id,
      type: e.eventType,
      name: e.name,
      severity: e.severity,
      fromState: e.fromState,
      toState: e.toState,
      toolName: e.toolName,
      llmModel: e.llmModel,
      promptHash: e.promptHash,
      inputTokens: e.inputTokens,
      outputTokens: e.outputTokens,
      costCents: e.costCents,
      latencyMs: e.latencyMs,
      payload: e.payload,
      createdAt: e.createdAt,
    }));
}

export async function getRunTrace(runId: string): Promise<RunTraceDTO | null> {
  const run = runs.find((r) => r.id === runId);
  if (!run) return settle(null);
  const vendor = vendors.find((v) => v.id === run.vendorId)!;
  return settle({
    runId: run.id,
    vendorId: run.vendorId,
    vendorName: vendor.name,
    vendorRole: vendor.vendorRole,
    state: run.state,
    status: run.status,
    trigger: run.trigger,
    dueDate: run.dueDate,
    startedAt: run.startedAt,
    updatedAt: run.updatedAt,
    completedAt: run.completedAt,
    budget: {
      outreachEmailCount: run.outreachEmailCount,
      maxOutreach: organization.settings.maxOutreach,
      llmCallCount: run.llmCallCount,
      maxLlmCallsPerDoc: organization.settings.maxLlmPerDoc,
      costCentsSpent: run.costCentsSpent,
      budgetCostCapCents: run.budgetCostCapCents,
    },
    events: toEventDTO(run.id),
  });
}

export async function getRunsForVendor(vendorId: string): Promise<RunTraceDTO[]> {
  const vendorRuns = runs.filter((r) => r.vendorId === vendorId);
  const traces = await Promise.all(vendorRuns.map((r) => getRunTrace(r.id)));
  return traces.filter((t): t is RunTraceDTO => t !== null);
}

// ---------------------------------------------------------------------------
// ReviewQueueItemDTO
// ---------------------------------------------------------------------------

function parsedLineFor(runId: string, coverageType: string): ParsedLineDTO | null {
  const extraction = coiExtractions.find((e) => e.runId === runId && e.isCurrent);
  if (!extraction) return null;
  const line = extraction.extracted.lines.find((l) => l.coverageType === coverageType);
  if (!line) return null;
  return {
    coverageType: line.coverageType,
    eachOccurrence: line.eachOccurrence,
    aggregate: line.aggregate,
    additionalInsured: line.additionalInsured,
    waiverOfSubrogation: line.waiverOfSubrogation,
    primaryNoncontributory: line.primaryNoncontributory,
    confidence: extraction.fieldConfidence[coverageType] ?? null,
  };
}

function buildComparison(runId: string, vendorId: string): LineComparisonDTO[] {
  const validation = coiValidations.find((v) => v.runId === runId);
  const required = requirementLines(vendorId);
  return required.map((req) => {
    const lineResult = validation?.lineResults.find((lr) => lr.vendorCoverageRequirementId === req.vendorCoverageRequirementId);
    const parsed = parsedLineFor(runId, req.coverageType);
    return {
      coverageType: req.coverageType,
      required: req,
      parsed,
      pass: lineResult?.pass ?? false,
      severity: lineResult?.severity ?? (req.sourceComplianceRequirementId ? "info" : "error"),
      note: lineResult?.note ?? (req.sourceComplianceRequirementId ? null : "No verified requirement on file backs this line -- Rowan will not validate against a guessed minimum."),
    };
  });
}

export async function getReviewQueue(): Promise<ReviewQueueItemDTO[]> {
  const open = escalations.filter((e) => e.status === "open");
  const items: ReviewQueueItemDTO[] = open.map((esc) => {
    const vendor = vendors.find((v) => v.id === esc.vendorId)!;
    const run = runs.find((r) => r.id === esc.runId);
    const doc = run?.coiDocumentId ? coiDocuments.find((d) => d.id === run.coiDocumentId) ?? null : null;
    const validation = coiValidations.find((v) => v.runId === esc.runId);
    const extraction = coiExtractions.find((e) => e.runId === esc.runId && e.isCurrent);
    return {
      escalationId: esc.id,
      runId: esc.runId,
      vendorId: esc.vendorId,
      vendorName: vendor.name,
      vendorRole: vendor.vendorRole,
      kind: esc.kind,
      reasonCode: esc.reasonCode,
      severity: esc.severity,
      summary: esc.summary,
      status: esc.status,
      createdAt: esc.createdAt,
      document: doc ? toDocumentRef(doc) : null,
      comparison: esc.kind === "needs_human_review" ? buildComparison(esc.runId, esc.vendorId) : [],
      flags: validation?.flags ?? [],
      faithfulnessOk: validation?.faithfulnessOk ?? true,
      overallConfidence: extraction?.overallConfidence ?? null,
    };
  });
  return settle(items.sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()));
}

export async function getReviewQueueItem(escalationId: string): Promise<ReviewQueueItemDTO | null> {
  const items = await getReviewQueue();
  return items.find((i) => i.escalationId === escalationId) ?? null;
}

// ---------------------------------------------------------------------------
// Run-trace evidence -- the coverage comparison + source document for a run,
// independent of whether it produced an open escalation. Reused by the run
// detail / trace timeline screen so a passing run (e.g. Hernandez Plumbing)
// shows the same parsed-vs-required evidence a failing one does.
// ---------------------------------------------------------------------------

export async function getRunComparison(runId: string, vendorId: string): Promise<LineComparisonDTO[]> {
  return settle(buildComparison(runId, vendorId));
}

export async function getRunDocument(runId: string): Promise<DocumentRef | null> {
  const run = runs.find((r) => r.id === runId);
  const doc = run?.coiDocumentId ? coiDocuments.find((d) => d.id === run.coiDocumentId) : coiDocuments.find((d) => d.runId === runId);
  return settle(doc ? toDocumentRef(doc) : null);
}

export async function getRunExtractionConfidence(runId: string): Promise<number | null> {
  const extraction = coiExtractions.find((e) => e.runId === runId && e.isCurrent);
  return settle(extraction?.overallConfidence ?? null);
}

// ---------------------------------------------------------------------------
// ActivityFeedItemDTO -- the hero surface. Hand-composed per run so headlines
// read like a colleague's work log rather than raw event dumps; each still
// carries a runId (-> trace) and evidence refs back to the source document.
// ---------------------------------------------------------------------------

interface FeedSeed {
  runId: string;
  vendorId: string;
  kind: ActivityFeedItemKind;
  headline: string;
  detail: string | null;
  occurredAt: string;
  actionRequired: boolean;
  evidenceDocId?: string;
  validTo?: string | null;
  sourceCitation?: string | null;
}

const feedSeeds: FeedSeed[] = [
  {
    runId: "run_hernandez_2026a",
    vendorId: "ven_hernandez",
    kind: "run_filed",
    headline: "Renewed COI for Hernandez Plumbing — valid through Mar 2027 — filed.",
    detail: "General liability, workers' comp, and auto all checked out against San Francisco requirements. No action needed.",
    occurredAt: "2026-07-15T18:26:05Z",
    actionRequired: false,
    evidenceDocId: "doc_hernandez_v3",
    validTo: "2027-03-15",
    sourceCitation: "SF Admin Code Ch. 38, as applied by Meridian PM policy v3 §2.2",
  },
  {
    runId: "run_titan_2026a",
    vendorId: "ven_titan_gc",
    kind: "escalated_to_pm",
    headline: "Titan General Contracting's certificate is in, but Rowan can't validate one line.",
    detail: "No verified umbrella/excess requirement on file for a general contractor at an Oakland HOA property — needs a decision, not a guess.",
    occurredAt: "2026-07-15T10:12:05Z",
    actionRequired: true,
    evidenceDocId: "doc_titan_v1",
    sourceCitation: null,
  },
  {
    runId: "run_apex_2026a",
    vendorId: "ven_apex_roofing",
    kind: "needs_human_review",
    headline: "Apex Roofing's renewed certificate falls short on coverage — flagged for your review.",
    detail: "General liability is $1,000,000, below the $2,000,000 San Francisco minimum, and Meridian isn't listed as additional insured.",
    occurredAt: "2026-07-16T13:08:25Z",
    actionRequired: true,
    evidenceDocId: "doc_apex_v2",
    sourceCitation: "SF Admin Code Ch. 38, as applied by Meridian PM policy v3 §2.2",
  },
  {
    runId: "run_guardian_2026a",
    vendorId: "ven_guardian_pest",
    kind: "escalated_to_pm",
    headline: "Guardian Pest Control hasn't responded after 3 emails — coverage lapsed 7/10.",
    detail: "Rowan has stopped emailing at the outreach cap. Needs your call: keep chasing, reach them another way, or pause the vendor.",
    occurredAt: "2026-07-17T09:00:05Z",
    actionRequired: true,
    evidenceDocId: undefined,
    sourceCitation: null,
  },
  {
    runId: "run_ridgeline_2026a",
    vendorId: "ven_ridgeline_hvac",
    kind: "escalated_to_pm",
    headline: "Ridgeline HVAC & Air's renewal hit an error and needs a look.",
    detail: "An inbound reply reused a reply-token from a completed run. Rowan refused to act rather than risk misfiling — paused for recovery.",
    occurredAt: "2026-07-17T11:02:00Z",
    actionRequired: true,
    sourceCitation: null,
  },
  {
    runId: "run_cleanpro_2026a",
    vendorId: "ven_cleanpro",
    kind: "needs_human_review",
    headline: "CleanPro's certificate scan was too unclear to read reliably — flagged rather than guessed.",
    detail: "General liability read fine; workers' comp figures came back at 41% confidence, below the 80% bar. Requesting a clearer copy or a manual read.",
    occurredAt: "2026-07-14T16:34:15Z",
    actionRequired: true,
    evidenceDocId: "doc_cleanpro_v2",
    sourceCitation: null,
  },
  {
    runId: "run_coastal_2026a",
    vendorId: "ven_coastal",
    kind: "document_received",
    headline: "Coastal Cleaning Crew's renewed certificate came in — reading it now.",
    detail: "Received this morning; extraction in progress. Rowan will validate against Sunset Row Homes requirements once parsed.",
    occurredAt: "2026-07-18T08:42:15Z",
    actionRequired: false,
    evidenceDocId: "doc_coastal_v2",
    sourceCitation: null,
  },
  {
    runId: "run_martinez_2026a",
    vendorId: "ven_martinez",
    kind: "follow_up_sent",
    headline: "Sent a second reminder to Martinez Landscaping — no response yet.",
    detail: "First request went out 6/20. One follow-up remaining before this needs to be escalated.",
    occurredAt: "2026-07-16T09:00:05Z",
    actionRequired: false,
    sourceCitation: null,
  },
  {
    runId: "run_bayarea_2026a",
    vendorId: "ven_bayarea_hvac",
    kind: "renewal_due_soon",
    headline: "Bay Area HVAC Co's coverage expires Aug 10 — Rowan will reach out today.",
    detail: "Entered the 30-day renewal window; first outreach email is queued for the next scheduler run.",
    occurredAt: "2026-07-18T09:00:00Z",
    actionRequired: false,
    sourceCitation: null,
  },
];

export async function getActivityFeed(): Promise<ActivityFeedItemDTO[]> {
  const items: ActivityFeedItemDTO[] = feedSeeds.map((seed) => {
    const vendor = vendors.find((v) => v.id === seed.vendorId)!;
    const doc = seed.evidenceDocId ? coiDocuments.find((d) => d.id === seed.evidenceDocId) ?? null : null;
    const run = runs.find((r) => r.id === seed.runId)!;
    return {
      id: `feed_${seed.runId}`,
      runId: seed.runId,
      vendorId: seed.vendorId,
      vendorName: vendor.name,
      vendorRole: vendor.vendorRole,
      kind: seed.kind,
      headline: seed.headline,
      detail: seed.detail,
      state: run.state,
      severity: seed.actionRequired ? (seed.kind === "escalated_to_pm" ? "error" : "warn") : "info",
      occurredAt: seed.occurredAt,
      actionRequired: seed.actionRequired,
      evidence: {
        document: doc ? toDocumentRef(doc) : null,
        validTo: seed.validTo ?? null,
        sourceCitation: seed.sourceCitation ?? null,
      },
    };
  });
  return settle(items.sort((a, b) => new Date(b.occurredAt).getTime() - new Date(a.occurredAt).getTime()));
}

// ---------------------------------------------------------------------------
// Portfolio snapshot -- feeds the "at a glance" strip on the home screen.
// ---------------------------------------------------------------------------

export interface PortfolioSnapshot {
  totalVendors: number;
  compliant: number;
  expiringSoon: number;
  needsReview: number;
  escalated: number;
  openReviewCount: number;
  llmSpendCentsThisMonth: number;
}

export async function getPortfolioSnapshot(): Promise<PortfolioSnapshot> {
  const list = await getVendorList();
  const openReview = escalations.filter((e) => e.status === "open");
  const spend = agentEvents
    .filter((e) => e.costCents && new Date(e.createdAt).getUTCMonth() === MOCK_MONTH)
    .reduce((sum, e) => sum + (e.costCents ?? 0), 0);
  return settle({
    totalVendors: list.length,
    compliant: list.filter((v) => v.complianceStatus === "compliant").length,
    expiringSoon: list.filter((v) => v.complianceStatus === "expiring_soon").length,
    needsReview: list.filter((v) => v.complianceStatus === "needs_review").length,
    escalated: list.filter((v) => v.complianceStatus === "escalated" || v.complianceStatus === "no_requirements").length,
    openReviewCount: openReview.length,
    llmSpendCentsThisMonth: spend,
  });
}

const MOCK_MONTH = new Date("2026-07-18T00:00:00Z").getUTCMonth();

export async function getVendorsById(): Promise<Map<string, VendorStatusDTO>> {
  const list = await getVendorList();
  return new Map(list.map((v) => [v.id, v]));
}

// ---------------------------------------------------------------------------
// Onboarding support
// ---------------------------------------------------------------------------

export interface PropertyOption {
  id: string;
  name: string;
  jurisdiction: string;
}

export async function getPropertyOptions(): Promise<PropertyOption[]> {
  return settle(
    properties.map((p) => ({
      id: p.id,
      name: p.name,
      jurisdiction: p.hoaName ? `${p.city}, ${p.state} · ${p.hoaName}` : `${p.city}, ${p.state}`,
    })),
  );
}

/**
 * Mirrors ADR 0005's V1DeterministicRetriever predicate match (jurisdiction +
 * property type + vendor role -> compliance_requirements, most-specific row
 * per coverage_type wins) so onboarding can suggest a starting requirement
 * set instead of leaving Dana to type limits from memory. This is NOT an LLM
 * call -- it's the same deterministic retrieval the renewal agent itself
 * uses, which is why the onboarding UI labels it "Suggest from compliance
 * library" rather than "AI pre-fill" for this part of the flow.
 *
 * # ASSUMPTION: the task brief's "AI pre-fill" for onboarding refers to the
 * COI-import path (extracting an uploaded certificate), which is a visual
 * placeholder in this build since parse_document isn't wired up yet. The
 * requirements suggestion here is the one piece of "pre-fill" that's fully
 * real, because it's deterministic retrieval, not model output -- see ADR
 * 0005's fallback/faithfulness requirements.
 */
export async function getRequirementSuggestions(vendorId: string): Promise<{ found: boolean; lines: RequirementLineDTO[] }> {
  const vendor = vendors.find((v) => v.id === vendorId);
  if (!vendor) return settle({ found: false, lines: [] });
  const property = properties.find((p) => p.id === vendor.primaryPropertyId);
  if (!property) return settle({ found: false, lines: [] });

  const matches = complianceRequirements.filter(
    (cr) =>
      cr.active &&
      cr.jurisdictionState === property.state &&
      (cr.jurisdictionCity === null || cr.jurisdictionCity === property.city) &&
      (cr.jurisdictionHoa === null || cr.jurisdictionHoa === property.hoaName) &&
      (cr.propertyType === null || cr.propertyType === property.propertyType) &&
      (cr.vendorRole === null || cr.vendorRole === vendor.vendorRole),
  );

  const specificity = (cr: (typeof matches)[number]) =>
    (cr.jurisdictionCity ? 1 : 0) + (cr.jurisdictionHoa ? 1 : 0) + (cr.propertyType ? 1 : 0) + (cr.vendorRole ? 1 : 0);

  const byCoverageType = new Map<string, (typeof matches)[number]>();
  matches
    .sort((a, b) => specificity(b) - specificity(a))
    .forEach((cr) => {
      if (!byCoverageType.has(cr.coverageType)) byCoverageType.set(cr.coverageType, cr);
    });

  const lines: RequirementLineDTO[] = Array.from(byCoverageType.values()).map((cr) => ({
    vendorCoverageRequirementId: `suggested_${cr.id}`,
    coverageType: cr.coverageType,
    minEachOccurrence: cr.minEachOccurrence,
    minAggregate: cr.minAggregate,
    requiresAdditionalInsured: cr.requiresAdditionalInsured,
    requiresWaiverOfSubrogation: cr.requiresWaiverOfSubrogation,
    requiresPrimaryNoncontributory: cr.requiresPrimaryNoncontributory,
    sourceComplianceRequirementId: cr.id,
    sourceCitation: cr.sourceCitation,
    sourceUrl: cr.sourceUrl,
    lastVerifiedAt: cr.lastVerifiedAt,
    confirmedByPm: false,
  }));

  return settle({ found: lines.length > 0, lines });
}
