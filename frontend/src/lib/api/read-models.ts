/**
 * Real read-model fetchers -- the live-backend counterpart to
 * `lib/mock/read-models.ts`. Every exported function here keeps the exact
 * name/signature/return shape its mock sibling had, so every Server
 * Component that previously did `import { getX } from "@/lib/mock/read-models"`
 * only needed its import source changed to `@/lib/api/read-models"` (see the
 * page.tsx files under `app/(app)/`) -- no call-site shape changes.
 *
 * Backed by `backend/app/api/reads.py`'s 4 read-model DTO routes (ADR 0003),
 * documented in `backend/README.md`'s "REST API" section. Two gaps in that
 * surface are flagged inline below rather than papered over: no property
 * list read model (blocks a live onboarding property picker) and no
 * validation-comparison route for a run that isn't a currently-open
 * escalation (blocks trace-page evidence for passed/filed runs).
 */

import { apiFetch, apiFetchOrNull } from "./client";
import type {
  ActivityFeedItemDTO,
  ComplianceObligationDTO,
  DocumentRef,
  LineComparisonDTO,
  ReviewQueueItemDTO,
  RunTraceDTO,
  VendorStatusDTO,
} from "@/lib/types";

// ---------------------------------------------------------------------------
// Document evidence -- rewrite every DocumentRef.url to the local proxy
// route (`app/api/documents/[documentId]/route.ts`) so it's actually
// loadable from the browser (cross-origin + the org-header auth stub both
// rule out linking straight at the backend's download route). See that
// route's docstring for the security rationale.
// ---------------------------------------------------------------------------

function remapDocumentRef(doc: DocumentRef): DocumentRef {
  return { ...doc, url: `/api/documents/${doc.documentId}` };
}

function remapVendorStatus(v: VendorStatusDTO): VendorStatusDTO {
  return {
    ...v,
    currentCoi: v.currentCoi ? { ...v.currentCoi, document: remapDocumentRef(v.currentCoi.document) } : null,
    history: v.history.map((h) => ({ ...h, document: remapDocumentRef(h.document) })),
  };
}

function remapActivityFeedItem(item: ActivityFeedItemDTO): ActivityFeedItemDTO {
  return {
    ...item,
    evidence: {
      ...item.evidence,
      document: item.evidence.document ? remapDocumentRef(item.evidence.document) : null,
    },
  };
}

function remapReviewQueueItem(item: ReviewQueueItemDTO): ReviewQueueItemDTO {
  return { ...item, document: item.document ? remapDocumentRef(item.document) : null };
}

// ---------------------------------------------------------------------------
// ActivityFeedItemDTO -- home / hero surface
// ---------------------------------------------------------------------------

export async function getActivityFeed(limit = 50): Promise<ActivityFeedItemDTO[]> {
  const items = await apiFetch<ActivityFeedItemDTO[]>(`/api/v1/activity-feed?limit=${limit}`);
  return items.map(remapActivityFeedItem);
}

// ---------------------------------------------------------------------------
// Portfolio snapshot -- feeds the "at a glance" strip on the home screen.
// No single backend endpoint returns this rollup; assembled here from the
// vendor list + review queue, both already org-scoped reads.
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
  const [vendors, needsReview, escalated] = await Promise.all([
    getVendorList(),
    apiFetch<ReviewQueueItemDTO[]>(`/api/v1/reviews?kind=needs_human_review`),
    apiFetch<ReviewQueueItemDTO[]>(`/api/v1/reviews?kind=escalated_to_pm`),
  ]);
  return {
    totalVendors: vendors.length,
    compliant: vendors.filter((v) => v.complianceStatus === "compliant").length,
    expiringSoon: vendors.filter((v) => v.complianceStatus === "expiring_soon").length,
    needsReview: vendors.filter((v) => v.complianceStatus === "needs_review").length,
    escalated: vendors.filter((v) => v.complianceStatus === "escalated" || v.complianceStatus === "no_requirements").length,
    openReviewCount: needsReview.length + escalated.length,
    // GAP (flag to tech lead / backend-engineer): CLAUDE.md's Observability
    // section calls for a "daily rollup ... total LLM spend", but no
    // backend read-model aggregates spend across runs org-wide yet --
    // RunTraceDTO.budget.costCentsSpent is per-run only, and there's no
    // "sum agent_events.cost_cents this month for this org" route. Zero
    // here is an honest "unknown," never a fabricated number.
    llmSpendCentsThisMonth: 0,
  };
}

// ---------------------------------------------------------------------------
// VendorStatusDTO -- vendor list + detail
// ---------------------------------------------------------------------------

export async function getVendorList(): Promise<VendorStatusDTO[]> {
  const vendors = await apiFetch<VendorStatusDTO[]>(`/api/v1/vendors`);
  return vendors.map(remapVendorStatus);
}

export async function getVendorStatus(vendorId: string): Promise<VendorStatusDTO | null> {
  const vendor = await apiFetchOrNull<VendorStatusDTO>(`/api/v1/vendors/${vendorId}`);
  return vendor ? remapVendorStatus(vendor) : null;
}

// ---------------------------------------------------------------------------
// RunTraceDTO -- run detail / trace timeline
// ---------------------------------------------------------------------------

export async function getRunTrace(runId: string): Promise<RunTraceDTO | null> {
  return apiFetchOrNull<RunTraceDTO>(`/api/v1/runs/${runId}/trace`);
}

// ---------------------------------------------------------------------------
// ReviewQueueItemDTO -- human review queue
// ---------------------------------------------------------------------------

export async function getReviewQueue(): Promise<ReviewQueueItemDTO[]> {
  // The backend's GET /reviews defaults `kind` to "needs_human_review" only
  // (app/api/reads.py) -- the mock's getReviewQueue() returned every open
  // escalation regardless of kind (app-shell's sidebar badge counts both),
  // so fetch both kinds explicitly and merge to keep that behavior.
  const [needsReview, escalated] = await Promise.all([
    apiFetch<ReviewQueueItemDTO[]>(`/api/v1/reviews?kind=needs_human_review`),
    apiFetch<ReviewQueueItemDTO[]>(`/api/v1/reviews?kind=escalated_to_pm`),
  ]);
  return [...needsReview, ...escalated]
    .map(remapReviewQueueItem)
    .sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime());
}

export async function getReviewQueueItem(escalationId: string): Promise<ReviewQueueItemDTO | null> {
  const item = await apiFetchOrNull<ReviewQueueItemDTO>(`/api/v1/reviews/${escalationId}`);
  return item ? remapReviewQueueItem(item) : null;
}

async function findOpenReviewItemForRun(runId: string): Promise<ReviewQueueItemDTO | null> {
  const items = await getReviewQueue();
  return items.find((i) => i.runId === runId) ?? null;
}

/**
 * GAP (flagged to tech lead / backend-engineer): the backend has no
 * read-model route exposing line-by-line coverage comparison evidence for a
 * run that ISN'T currently an open escalation. `coi_validations` rows are
 * persisted for every validated run regardless of pass/fail
 * (`app/api/read_models.py::_assemble_review_queue_item` reads them, but
 * only via an escalation row) -- `RunTraceDTO` doesn't carry them, and
 * there's no "get validation by run_id" route. Concretely: a PASSED (filed)
 * run's trace page currently cannot show the same parsed-vs-required
 * evidence a failed one does, which is exactly the gap CLAUDE.md's "every
 * claim carries evidence" bar cares about for this screen.
 *
 * Degrades honestly rather than fabricating: only runs with a currently-open
 * escalation get comparison data here; everything else gets `[]`, which
 * `runs/[runId]/page.tsx` already renders as "no comparison card" (see its
 * `comparison.length > 0 ? ... : null`) rather than a fake one.
 */
export async function getRunComparison(runId: string, vendorId: string): Promise<LineComparisonDTO[]> {
  // vendorId is part of the signature for call-site parity with the mock
  // (and in case a future "get validation by run + vendor" route needs it)
  // but isn't needed by today's review-queue-backed lookup.
  void vendorId;
  const item = await findOpenReviewItemForRun(runId);
  return item?.comparison ?? [];
}

/** Same gap as `getRunComparison` above -- only available when the run has
 * a currently-open escalation carrying a document reference. */
export async function getRunDocument(runId: string): Promise<DocumentRef | null> {
  const item = await findOpenReviewItemForRun(runId);
  return item?.document ?? null;
}

// ---------------------------------------------------------------------------
// Onboarding support
// ---------------------------------------------------------------------------

export interface PropertyOption {
  id: string;
  name: string;
  jurisdiction: string;
}

/**
 * GAP (flagged to tech lead / backend-engineer): there is no
 * `GET /api/v1/properties`-shaped read model in the current REST API (ADR
 * 0003 lists exactly 4 read DTOs -- ActivityFeedItemDTO, VendorStatusDTO,
 * RunTraceDTO, ReviewQueueItemDTO -- none a property list) and no `AddProperty`
 * command either, so onboarding's "primary property" picker has no live
 * data source. Returns an empty list rather than inventing an endpoint or
 * hardcoding the seed property's UUID (migrations/0009_seed.sql) -- that
 * would silently break for any other org. `AddVendorForm` degrades this to
 * an optional field with an inline note when the list is empty, matching
 * the backend's `AddVendorRequest.primary_property_id: UUID | None`
 * (nullable) rather than blocking vendor creation on a picker that can't be
 * populated.
 */
// ---------------------------------------------------------------------------
// ComplianceObligationDTO -- compliance knowledge base
// ---------------------------------------------------------------------------

export async function getComplianceObligations(): Promise<ComplianceObligationDTO[]> {
  return apiFetch<ComplianceObligationDTO[]>("/api/v1/compliance/obligations");
}

export async function getPropertyOptions(): Promise<PropertyOption[]> {
  return [];
}

// ---------------------------------------------------------------------------
// MeDTO -- caller identity + role, backs the user menu and the owner-only
// team-settings gate. Role-aware UI built from this is COSMETIC ONLY: the
// backend's `require_role` (app/api/deps.py) is the real enforcement point
// and returns 403 regardless of what this says. Hiding a button here is not
// a permission -- it is a courtesy so the UI doesn't offer an action that
// will just fail.
// ---------------------------------------------------------------------------

export interface MeDTO {
  userId: string;
  organizationId: string;
  email: string;
  role: "owner" | "assistant";
}

export async function getMe(): Promise<MeDTO> {
  return apiFetch<MeDTO>("/api/v1/me");
}

// ---------------------------------------------------------------------------
// InvitationDTO -- pending team invitations, owner-only per policy.py's
// COMMAND_ROLES (invite_user / list_invitations / revoke_invitation).
// ---------------------------------------------------------------------------

export interface InvitationDTO {
  id: string;
  email: string;
  role: string;
  expiresAt: string;
}

export async function getPendingInvitations(): Promise<InvitationDTO[]> {
  return apiFetch<InvitationDTO[]>("/api/v1/invitations");
}
