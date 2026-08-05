"use server";

import { redirect } from "next/navigation";

import { apiFetch } from "@/lib/api/client";
import { createServerClient } from "@/lib/supabase/server";

/**
 * Sign up, then create the Rowan organization for the new user, in ONE
 * server round trip.
 *
 * These two steps are deliberately NOT split across the browser/server
 * boundary. The earlier version called `supabase.auth.signUp` in the browser
 * and then invoked a server action to bootstrap, on the assumption that "the
 * session cookie now exists" by the time the action ran. It does not: the
 * browser client writes the cookie locally, but the in-flight server action
 * request was already composed without it, so `getSession()` returned null
 * server-side and `apiFetch` threw `ApiError(401, "Not authenticated")` —
 * surfacing to the user as Next's opaque "An unexpected response was
 * received from the server."
 *
 * Doing `signUp` here, through the cookie-backed server client, means the
 * session is written by the same handler the subsequent `apiFetch` reads
 * from. There is no window between the two.
 *
 * # ASSUMPTION: email confirmation is disabled, so `signUp` returns a live
 * session immediately. With confirmation ON, there is no session until the
 * user clicks the link, and this flow needs an explicit "check your email"
 * state plus a post-confirmation bootstrap. Local Supabase disables it by
 * default; a hosted project does NOT.
 */
export async function signUpAndBootstrap(formData: FormData) {
  const organizationName = String(formData.get("organizationName") ?? "").trim();
  const fullName = String(formData.get("fullName") ?? "").trim() || null;
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");

  if (!organizationName) return { error: "Enter a name for your business." };
  if (!email || !password) return { error: "Enter an email address and password." };

  const supabase = await createServerClient();
  const { data, error: signUpError } = await supabase.auth.signUp({ email, password });

  if (signUpError) {
    return { error: signUpError.message };
  }

  if (!data.session) {
    // Email confirmation is enabled on this project — see the ASSUMPTION
    // above. Say so plainly rather than failing with a 401 three steps later.
    return {
      error:
        "Check your email to confirm your account, then sign in. " +
        "(Rowan cannot finish setting up your organization until then.)",
    };
  }

  try {
    await apiFetch("/api/v1/orgs/bootstrap", {
      method: "POST",
      body: { organizationName, fullName },
    });
  } catch (e) {
    // The Supabase account now exists but has no Rowan organization. That
    // is a recoverable state -- `bootstrapExistingUser` below finishes the
    // job on next sign-in -- but tell the user something true rather than
    // leaving them in silent limbo.
    const message = e instanceof Error ? e.message : "Something went wrong.";
    return {
      error: `Your account was created, but setting up your organization failed: ${message}. Sign in to finish setup.`,
    };
  }

  redirect("/onboarding");
}

/**
 * Finish setup for a user who has a Supabase account but no Rowan
 * organization — the state left behind if `signUpAndBootstrap` failed
 * partway, or if someone signed up against a misconfigured server.
 *
 * Without this there is no recovery path at all: the account can sign in,
 * every page 401s, and signing up again reports "already registered".
 */
export async function bootstrapExistingUser(formData: FormData) {
  const organizationName = String(formData.get("organizationName") ?? "").trim();
  const fullName = String(formData.get("fullName") ?? "").trim() || null;

  if (!organizationName) return { error: "Enter a name for your business." };

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
 * Sign in an existing user. Server-side for the same reason as signup: the
 * session cookie is written by the handler that later requests will read.
 */
export async function signIn(formData: FormData) {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const next = String(formData.get("next") ?? "/") || "/";

  const supabase = await createServerClient();
  const { error } = await supabase.auth.signInWithPassword({ email, password });

  if (error) {
    // Deliberately generic: distinguishing "no such account" from "wrong
    // password" is an account-enumeration oracle.
    return { error: "That email and password don't match an account." };
  }

  // Only ever redirect to a path on this origin -- an absolute URL here
  // would be an open-redirect.
  redirect(next.startsWith("/") && !next.startsWith("//") ? next : "/");
}

/**
 * Redeem an invite token for the currently-authenticated user.
 *
 * SECURITY: the backend returns one generic message for every rejection
 * reason (expired / already used / wrong email / unknown token) --
 * distinguishing them here would leak which case applied. Surface the
 * backend's message verbatim; do not add detail. The token itself is a
 * credential -- it is never logged.
 */
export async function signUpAndAcceptInvitation(token: string, formData: FormData) {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");

  if (!email || !password) return { error: "Enter an email address and password." };

  const supabase = await createServerClient();
  const { data, error: signUpError } = await supabase.auth.signUp({ email, password });

  if (signUpError) return { error: signUpError.message };
  if (!data.session) {
    return { error: "Check your email to confirm your account, then open this invitation link again." };
  }

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
