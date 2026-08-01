"use server";

/**
 * Server Actions backing the team-settings page. Same transport pattern as
 * `app/actions.ts`: typed call in, `apiFetch` to the real backend, revalidate
 * the page so the pending-invitations list reflects the mutation.
 *
 * SECURITY: these hit owner-only backend routes
 * (`POST /api/v1/invitations`, `POST /api/v1/invitations/{id}/revoke`, both
 * gated by `require_role(Command.invite_user | Command.revoke_invitation)`
 * in app/api/deps.py). An assistant who somehow reaches this page (the
 * page-level redirect is cosmetic, not a security boundary) gets a 403 from
 * the backend, surfaced here as `{ error }` -- never silently swallowed.
 */

import { revalidatePath } from "next/cache";

import { apiFetch, ApiError } from "@/lib/api/client";
import type { InvitationDTO } from "@/lib/api/read-models";

export async function inviteAssistant(
  formData: FormData,
): Promise<{ error: string } | { error?: undefined }> {
  const email = String(formData.get("email") ?? "").trim();
  if (!email) {
    return { error: "Enter an email address to invite." };
  }

  try {
    await apiFetch<InvitationDTO>("/api/v1/invitations", {
      method: "POST",
      body: { email },
    });
  } catch (e) {
    if (e instanceof ApiError) {
      // 409 = an invitation is already pending for this email (backend's
      // exact wording); 403 = the cosmetic page guard was bypassed and the
      // real enforcement caught it. Both are human-readable as-is.
      return { error: typeof e.detail === "string" ? e.detail : e.message };
    }
    return { error: e instanceof Error ? e.message : "Something went wrong inviting this person." };
  }

  revalidatePath("/settings/team");
  return {};
}

export async function revokeInvitation(id: string): Promise<{ error: string } | { error?: undefined }> {
  try {
    await apiFetch<void>(`/api/v1/invitations/${id}/revoke`, { method: "POST" });
  } catch (e) {
    if (e instanceof ApiError) {
      return { error: typeof e.detail === "string" ? e.detail : e.message };
    }
    return { error: e instanceof Error ? e.message : "Something went wrong revoking this invitation." };
  }

  revalidatePath("/settings/team");
  return {};
}
