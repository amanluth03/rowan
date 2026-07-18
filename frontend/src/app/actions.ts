"use server";

/**
 * Server Actions -- the concrete transport for the Interface -> Orchestration
 * command seam (ADR 0003) in this build. A component calls one of these with
 * a typed command from `lib/commands.ts`; today the body runs against the
 * mock store (`lib/mock/store.ts`). Wiring the real backend later means
 * swapping each body for `fetch(`${API_BASE}/api/commands/...`)` -- the
 * exported function signatures (command in, CommandResult out) do not change,
 * so no calling component needs to change.
 *
 * SECURITY (flagged at review, not yet applicable against the mock store):
 * command shapes deliberately carry no organization_id -- when these bodies
 * are swapped for real fetch() calls, org must be derived server-side from
 * the authenticated session (never accepted from the client), and these
 * command endpoints must be rate-limited per CLAUDE.md's Security section.
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
import * as store from "@/lib/mock/store";
import { getRequirementSuggestions } from "@/lib/mock/read-models";
import type { RequirementLineDTO } from "@/lib/types";

function revalidateAfterCommand() {
  revalidatePath("/");
  revalidatePath("/vendors");
  revalidatePath("/review");
  revalidatePath("/runs", "layout");
  revalidatePath("/vendors", "layout");
}

export async function approveReviewAction(cmd: ApproveReviewCommand): Promise<CommandResult> {
  const result = store.approveReview(cmd);
  revalidateAfterCommand();
  return result;
}

export async function rejectReviewAction(cmd: RejectReviewCommand): Promise<CommandResult> {
  const result = store.rejectReview(cmd);
  revalidateAfterCommand();
  return result;
}

export async function requestRevisionAction(cmd: RequestRevisionCommand): Promise<CommandResult> {
  const result = store.requestRevision(cmd);
  revalidateAfterCommand();
  return result;
}

export async function resolveEscalationAction(cmd: ResolveEscalationCommand): Promise<CommandResult> {
  const result = store.resolveEscalation(cmd);
  revalidateAfterCommand();
  return result;
}

export async function pauseRunAction(cmd: PauseRunCommand): Promise<CommandResult> {
  const result = store.pauseRun(cmd);
  revalidateAfterCommand();
  return result;
}

export async function resumeRunAction(cmd: ResumeRunCommand): Promise<CommandResult> {
  const result = store.resumeRun(cmd);
  revalidateAfterCommand();
  return result;
}

export async function startRunAction(cmd: StartRunCommand): Promise<CommandResult<{ runId: string }>> {
  const result = store.startRun(cmd);
  revalidateAfterCommand();
  return result;
}

export async function addVendorAction(cmd: AddVendorCommand): Promise<CommandResult<{ vendorId: string }>> {
  const result = store.addVendor(cmd);
  revalidateAfterCommand();
  return result;
}

export async function setRequirementsAction(cmd: SetRequirementsCommand): Promise<CommandResult> {
  const result = store.setRequirements(cmd);
  revalidateAfterCommand();
  return result;
}

/** Read-only -- not a command. Backs the onboarding "suggest from compliance
 * library" affordance (ADR 0005's deterministic retriever, not an LLM call). */
export async function getRequirementSuggestionsAction(vendorId: string): Promise<{ found: boolean; lines: RequirementLineDTO[] }> {
  return getRequirementSuggestions(vendorId);
}
