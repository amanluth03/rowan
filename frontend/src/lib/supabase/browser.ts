/**
 * Browser Supabase client -- used only by the login, signup, and
 * accept-invite forms, which must call signUp/signInWithPassword directly.
 * Everything else in this app talks to the Rowan API from the server.
 */

"use client";

import { createBrowserClient as createSSRBrowserClient } from "@supabase/ssr";

export function createBrowserClient() {
  return createSSRBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
