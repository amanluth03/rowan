/**
 * Typed commands the Interface layer may send to Orchestration (ADR 0003:
 * "Interface -> Orchestration: typed commands only ... Never raw SQL, never a
 * tool call, never a prompt.").
 *
 * In this build these are executed by mock Server Actions
 * (`src/app/actions.ts`) against the in-memory fixture store. Swapping to the
 * real backend means pointing each `run*Command` function at
 * `POST /api/commands/...` instead of the mock store -- the command shapes
 * and call sites in components do not change.
 */

import type { CoverageType, VendorRole } from "./types";

export interface StartRunCommand {
  vendorId: string;
  trigger: "renewal_due" | "manual";
}

export interface PauseRunCommand {
  runId: string;
  reason?: string;
}

export interface ResumeRunCommand {
  runId: string;
}

export interface ApproveReviewCommand {
  escalationId: string;
  note?: string;
}

export interface RejectReviewCommand {
  escalationId: string;
  reason: string;
}

export interface RequestRevisionCommand {
  escalationId: string;
  message: string;
}

export interface ResolveEscalationCommand {
  escalationId: string;
  resolution: "resolved" | "keep_chasing";
  note?: string;
}

export interface AddVendorCommand {
  name: string;
  primaryEmail: string;
  vendorRole: VendorRole;
  /**
   * Nullable: the real backend's `AddVendorRequest.primary_property_id` is
   * optional (`UUID | None`). # ASSUMPTION / gap: there is no `GET
   * /api/v1/properties`-shaped read model in the current REST API (ADR 0003
   * lists only 4 read DTOs, none a property list), so onboarding has no live
   * way to populate a property picker -- flagged to backend/architect.
   * Submitting without one is a real, backend-supported degradation, not a
   * client-side hack: a vendor with `primary_property_id=null` just can't
   * use requirements auto-retrieval (ADR 0005) until a PM sets one another
   * way.
   */
  primaryPropertyId: string | null;
  notes?: string;
}

export interface SetRequirementsLine {
  coverageType: CoverageType;
  minEachOccurrence: number | null;
  minAggregate: number | null;
  requiresAdditionalInsured: boolean;
  requiresWaiverOfSubrogation: boolean;
  requiresPrimaryNoncontributory: boolean;
  /** Present when materialized from RequirementsRetriever; absent = PM override. */
  sourceComplianceRequirementId?: string | null;
}

export interface SetRequirementsCommand {
  vendorId: string;
  lines: SetRequirementsLine[];
}

/** Generic result envelope every command resolves to. */
export interface CommandResult<T = undefined> {
  ok: boolean;
  message: string;
  data?: T;
}
