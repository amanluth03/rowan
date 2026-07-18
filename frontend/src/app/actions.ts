"use server";

/**
 * Server Actions -- the concrete transport for the Interface -> Orchestration
 * command seam (ADR 0003). A component calls one of these with a typed
 * command from `lib/commands.ts`; bodies now call the real FastAPI backend
 * (`backend/app/api/commands.py`, ADR 0003's 9 typed commands) via
 * `lib/api/client.ts` instead of the `lib/mock/store.ts` fixture. Per this
 * file's original docstring, this was a body swap, not a rewrite -- every
 * exported function keeps its original signature (command in, CommandResult
 * out), so no calling component changed.
 *
 * SECURITY: command shapes deliberately carry no `organizationId` -- it is
 * resolved server-side, in exactly one place (`lib/api/config.ts::getOrgId`),
 * matching the backend's own `X-Rowan-Org-Id` dev-auth-stub seam
 * (`app/api/deps.py::get_organization_id`). Never accept `organizationId`
 * from client input. All routes are rate-limited on the backend side
 * (`app/api/deps.py::rate_limit`, 120 req/60s per client IP).
 *
 * Two real command-shape gaps found while wiring this up (flagged to tech
 * lead / backend-engineer, not silently routed around):
 *
 * 1. `RejectReviewCommand.reason` has nowhere to go -- the backend's
 *    `RejectReviewRequest` (app/api/schemas.py) only accepts `resolved_by`,
 *    not a reason/note. The UI still collects it (useful locally, and the
 *    field may get backend support later) but it is NOT currently persisted
 *    to the trace, unlike `RequestRevisionCommand.message`, which DOES map
 *    to a real field (`revision_reason`, threaded into the revision-request
 *    email template -- see `app/orchestration/runner.py`).
 * 2. `StartRunCommand` takes a `vendorId` (mock semantics: "create a new run
 *    for this vendor"), but the backend's `StartRun` command
 *    (`POST /api/v1/runs/{run_id}/start`) takes an existing `run_id` and
 *    fast-forwards ITS `monitoring -> renewal_due_soon` guard -- there is no
 *    "create an ad-hoc run" command, because `AddVendor` already creates the
 *    vendor's one long-lived run row (reused across renewal cycles, per
 *    backend/README.md). `startRunAction` below resolves `vendorId ->
 *    activeRun.runId` via a `GET /vendors/{id}` first to bridge this.
 */

import { revalidatePath } from "next/cache";
import type {
  AddVendorCommand,
  ApproveReviewCommand,
  CommandResult,
  PauseRunCommand,
  RejectReviewCommand,
  RequestRevisionCommand,
  ResolveEscalationCommand,
  ResumeRunCommand,
  SetRequirementsCommand,
  StartRunCommand,
} from "@/lib/commands";
import { apiFetch, ApiError } from "@/lib/api/client";
import type { RequirementLineDTO, VendorStatusDTO } from "@/lib/types";

function revalidateAfterCommand() {
  revalidatePath("/");
  revalidatePath("/vendors");
  revalidatePath("/review");
  revalidatePath("/runs", "layout");
  revalidatePath("/vendors", "layout");
}

/** Every command below is wrapped in this so a non-2xx backend response (a
 * guard rejection, a validation 422, a stale-escalation 409) becomes a
 * `{ ok: false, message }` CommandResult instead of an unhandled throw --
 * the backend's `HTTPException(detail=...)` strings are already
 * human-readable (see app/api/commands.py), so they're surfaced directly. */
async function runCommand<T = undefined>(fn: () => Promise<CommandResult<T>>): Promise<CommandResult<T>> {
  try {
    const result = await fn();
    revalidateAfterCommand();
    return result;
  } catch (e) {
    revalidateAfterCommand();
    if (e instanceof ApiError) {
      return { ok: false, message: typeof e.detail === "string" ? e.detail : e.message };
    }
    return { ok: false, message: e instanceof Error ? e.message : "Something went wrong talking to Rowan's backend." };
  }
}

interface ReviewActionResponse {
  escalationId: string;
  runId: string;
  runState: string;
}

interface RunActionResponse {
  runId: string;
  state: string;
  status: string;
}

// ---------------------------------------------------------------------------
// Review-queue commands (needs_human_review escalations)
// ---------------------------------------------------------------------------

export async function approveReviewAction(cmd: ApproveReviewCommand): Promise<CommandResult> {
  return runCommand(async () => {
    await apiFetch<ReviewActionResponse>(`/api/v1/reviews/${cmd.escalationId}/approve`, {
      method: "POST",
      body: {},
    });
    return { ok: true, message: "Approved. Rowan will file this certificate on your sign-off and return to monitoring." };
  });
}

export async function rejectReviewAction(cmd: RejectReviewCommand): Promise<CommandResult> {
  return runCommand(async () => {
    // NOTE: `cmd.reason` is not sent -- the backend's RejectReviewRequest has
    // no field for it yet. See this file's top docstring, gap #1.
    await apiFetch<ReviewActionResponse>(`/api/v1/reviews/${cmd.escalationId}/reject`, {
      method: "POST",
      body: {},
    });
    return { ok: true, message: "Rejected. This vendor is now parked in Escalated until you decide next steps." };
  });
}

export async function requestRevisionAction(cmd: RequestRevisionCommand): Promise<CommandResult> {
  return runCommand(async () => {
    await apiFetch<ReviewActionResponse>(`/api/v1/reviews/${cmd.escalationId}/request-revision`, {
      method: "POST",
      body: { revisionReason: cmd.message },
    });
    return { ok: true, message: "Revision requested. Rowan emailed the vendor with your note and is waiting on a reply." };
  });
}

// ---------------------------------------------------------------------------
// Escalation (PM-escalation) commands
// ---------------------------------------------------------------------------

export async function resolveEscalationAction(cmd: ResolveEscalationCommand): Promise<CommandResult> {
  return runCommand(async () => {
    await apiFetch<ReviewActionResponse>(`/api/v1/escalations/${cmd.escalationId}/resolve`, {
      method: "POST",
      body: { decision: cmd.resolution },
    });
    const message =
      cmd.resolution === "resolved"
        ? "Marked resolved. Rowan has returned this vendor to normal monitoring."
        : "Got it — Rowan will keep chasing this vendor for one more round.";
    return { ok: true, message };
  });
}

// ---------------------------------------------------------------------------
// Run lifecycle commands
// ---------------------------------------------------------------------------

export async function pauseRunAction(cmd: PauseRunCommand): Promise<CommandResult> {
  return runCommand(async () => {
    await apiFetch<RunActionResponse>(`/api/v1/runs/${cmd.runId}/pause`, { method: "POST" });
    return { ok: true, message: "Paused. Rowan will take no further automated action on this run until you resume it." };
  });
}

export async function resumeRunAction(cmd: ResumeRunCommand): Promise<CommandResult> {
  return runCommand(async () => {
    await apiFetch<RunActionResponse>(`/api/v1/runs/${cmd.runId}/resume`, { method: "POST" });
    return { ok: true, message: "Resumed. Rowan will pick this run back up on its next scheduled action." };
  });
}

export async function startRunAction(cmd: StartRunCommand): Promise<CommandResult<{ runId: string }>> {
  return runCommand(async () => {
    // Bridge vendorId -> runId -- see this file's top docstring, gap #2.
    const vendor = await apiFetch<VendorStatusDTO>(`/api/v1/vendors/${cmd.vendorId}`);
    if (!vendor.activeRun) {
      return { ok: false, message: "This vendor has no run to start -- unexpected, every vendor gets one at creation." };
    }
    const result = await apiFetch<RunActionResponse>(`/api/v1/runs/${vendor.activeRun.runId}/start`, {
      method: "POST",
    });
    return { ok: true, message: `Started a renewal run for ${vendor.name}.`, data: { runId: result.runId } };
  });
}

// ---------------------------------------------------------------------------
// Onboarding commands
// ---------------------------------------------------------------------------

interface AddVendorResponse {
  vendorId: string;
  runId: string;
  runState: string;
  replyToken: string;
  replyTokenExpiresAt: string;
}

export async function addVendorAction(cmd: AddVendorCommand): Promise<CommandResult<{ vendorId: string }>> {
  return runCommand(async () => {
    const result = await apiFetch<AddVendorResponse>(`/api/v1/vendors`, {
      method: "POST",
      body: {
        name: cmd.name,
        primaryEmail: cmd.primaryEmail || null,
        vendorRole: cmd.vendorRole,
        primaryPropertyId: cmd.primaryPropertyId,
        notes: cmd.notes ?? null,
      },
    });
    return {
      ok: true,
      message: `${cmd.name} added. Set coverage requirements next so Rowan knows what to validate against.`,
      data: { vendorId: result.vendorId },
    };
  });
}

interface SetRequirementsResponse {
  vendorId: string;
  requirements: RequirementLineDTO[];
}

export async function setRequirementsAction(cmd: SetRequirementsCommand): Promise<CommandResult> {
  return runCommand(async () => {
    await apiFetch<SetRequirementsResponse>(`/api/v1/vendors/${cmd.vendorId}/requirements`, {
      method: "POST",
      body: {
        lines: cmd.lines.map((l) => ({
          coverageType: l.coverageType,
          minEachOccurrence: l.minEachOccurrence,
          minAggregate: l.minAggregate,
          requiresAdditionalInsured: l.requiresAdditionalInsured,
          requiresWaiverOfSubrogation: l.requiresWaiverOfSubrogation,
          requiresPrimaryNoncontributory: l.requiresPrimaryNoncontributory,
          sourceComplianceRequirementId: l.sourceComplianceRequirementId ?? null,
        })),
      },
    });
    return { ok: true, message: `Saved ${cmd.lines.length} coverage requirement${cmd.lines.length === 1 ? "" : "s"}.` };
  });
}

/**
 * Read-only in the mock, but NOT in the real backend: there is no
 * preview-only "suggest without persisting" route. `SetRequirements` with
 * `lines` omitted BOTH retrieves from the compliance-requirements KB AND
 * immediately persists the result (`confirmed_by_pm=true` -- see ADR 0005 /
 * `app/orchestration/runner.py::set_requirements`'s docstring: "calling this
 * command IS the PM confirmation act"). Flagged to tech lead / backend-
 * engineer as a real gap: clicking "Suggest from compliance library" now
 * writes to the DB immediately rather than merely previewing, though the
 * two-step UX (suggest, edit, "Save requirements") still ends at the same
 * persisted state either way, since `set_requirements` upserts per
 * `coverage_type` rather than replacing wholesale.
 */
export async function getRequirementSuggestionsAction(vendorId: string): Promise<{ found: boolean; lines: RequirementLineDTO[] }> {
  try {
    const result = await apiFetch<SetRequirementsResponse>(`/api/v1/vendors/${vendorId}/requirements`, {
      method: "POST",
      body: {},
    });
    revalidateAfterCommand();
    return { found: result.requirements.length > 0, lines: result.requirements };
  } catch (e) {
    revalidateAfterCommand();
    // 422 = ADR 0005's fallback ("no verified requirements on file") -- not
    // an error state, just "nothing to suggest."
    if (e instanceof ApiError && e.status === 422) {
      return { found: false, lines: [] };
    }
    throw e;
  }
}
