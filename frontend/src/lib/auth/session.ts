/**
 * The single seam for "who is this request for" -- the direct replacement
 * for the frontend's old hardcoded-org-id dev-auth stub.
 *
 * Note what is deliberately absent: an organization id. The frontend never
 * names an org. It forwards an access token, and the BACKEND resolves which
 * org that token belongs to (app/api/deps.py::get_principal). That removes
 * the entire class of bug the old stub's docstring warned about -- a
 * client-supplied org id being treated as ground truth -- because the client
 * no longer has an org id to supply.
 */

import { redirect } from "next/navigation";

import { createServerClient } from "@/lib/supabase/server";

export interface RowanSession {
  accessToken: string;
  user: { id: string; email: string };
}

export async function getSession(): Promise<RowanSession | null> {
  const supabase = await createServerClient();

  // getUser() re-validates against the Supabase auth server. getSession()
  // alone trusts the cookie, which a compromised browser could forge --
  // only read the access token below once getUser() has confirmed a user.
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return null;

  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session?.access_token) return null;

  return {
    accessToken: session.access_token,
    user: { id: user.id, email: user.email ?? "" },
  };
}

export async function requireSession(): Promise<RowanSession> {
  const session = await getSession();
  if (!session) redirect("/login");
  return session;
}
