import { redirect } from "next/navigation";

import { ApiError } from "@/lib/api/client";
import { getMe } from "@/lib/api/read-models";
import { requireSession } from "@/lib/auth/session";

import { FinishSetupForm } from "./finish-setup-form";

/**
 * Guard for the recovery screen.
 *
 * Without this, /finish-setup is a dead end for anyone who already has an
 * organization: the form posts, the backend answers 409 "already
 * provisioned", and the user is stuck on a page whose only action can never
 * succeed. That is reachable by a bookmark, a back-button, a stale tab, or a
 * `?next=/finish-setup` left over from a sign-in redirect.
 *
 * So the page answers the question before rendering the form:
 *   - no Supabase session at all  -> /login (requireSession)
 *   - session, but no Rowan org   -> show the form (the state it exists for)
 *   - session AND an org          -> nothing to finish, go to the app
 */
export default async function FinishSetupPage() {
  await requireSession();

  try {
    await getMe();
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      return <FinishSetupForm />;
    }
    throw e;
  }

  redirect("/");
}
