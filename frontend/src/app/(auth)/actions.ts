"use server";

import { redirect } from "next/navigation";

import { apiFetch } from "@/lib/api/client";

/**
 * Called AFTER Supabase signUp succeeds on the client. Creates the Rowan
 * organization for the freshly-authenticated user and makes them its owner.
 *
 * Split this way because signUp must run in the browser (it sets the
 * session cookie), while org creation must run server-side against the
 * Rowan API with the resulting token.
 */
export async function bootstrapOrganization(formData: FormData) {
  const organizationName = String(formData.get("organizationName") ?? "").trim();
  const fullName = String(formData.get("fullName") ?? "").trim() || null;

  if (!organizationName) {
    return { error: "Enter a name for your business." };
  }

  try {
    await apiFetch("/api/v1/orgs/bootstrap", {
      method: "POST",
      body: { organizationName, fullName },
    });
  } catch (e) {
    const message = e instanceof Error ? e.message : "Something went wrong.";
    return { error: message };
  }

  redirect("/onboarding");
}

/**
 * Called AFTER Supabase signUp succeeds on the accept-invite page. Redeems
 * the invite token against the freshly-authenticated user, same
 * browser/server split as `bootstrapOrganization` above.
 *
 * SECURITY: the backend returns one generic message for every rejection
 * reason (expired / already used / wrong email / unknown token) --
 * distinguishing them here would leak which case applied. Surface the
 * backend's message verbatim; do not add detail. The token itself is a
 * credential -- it is never logged.
 */
export async function acceptInvitation(token: string) {
  try {
    await apiFetch("/api/v1/invitations/accept", {
      method: "POST",
      body: { token },
    });
  } catch (e) {
    const message = e instanceof Error ? e.message : "Something went wrong.";
    return { error: message };
  }
  redirect("/");
}
