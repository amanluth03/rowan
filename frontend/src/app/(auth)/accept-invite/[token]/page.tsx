"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { acceptInvitation } from "@/app/(auth)/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { createBrowserClient } from "@/lib/supabase/browser";

// SECURITY: the org this invite belongs to is deliberately unknown to an
// unauthenticated token holder -- the backend's /invitations/accept
// response carries only IDs, never a name, so there is nothing to display
// here beyond this generic line. Do not add the org name once it becomes
// available post-acceptance; that would defeat the point.
const INVITE_COPY = "You've been invited to join a team on Rowan. Create your account to accept.";

export default function AcceptInvitePage() {
  const router = useRouter();
  // `useParams` (client-side) rather than the `params` prop -- this page
  // must be a Client Component (it calls supabase.auth.signUp directly), and
  // in Next.js 16 a Client Component page's `params` prop is a Promise that
  // needs React's `use()`; `useParams()` is the documented alternative for
  // reading route params anywhere in a Client Component tree.
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setPending(true);
    setError(null);

    const form = new FormData(e.currentTarget);
    const supabase = createBrowserClient();
    const { error: signUpError } = await supabase.auth.signUp({
      email: String(form.get("email")),
      password: String(form.get("password")),
    });

    if (signUpError) {
      setError(signUpError.message);
      setPending(false);
      return;
    }

    // The session cookie now exists, so the server action can redeem the
    // invite against this user. NOTE: the token never appears in a log
    // statement or is rendered anywhere on this page -- it is a credential.
    // No other form fields are needed server-side -- acceptance is keyed
    // purely on the token against the now-authenticated caller.
    const result = await acceptInvitation(token);
    if (result?.error) {
      // The backend returns one generic message for every rejection reason
      // (expired / already used / wrong email / unknown token). Surface it
      // as-is; do not try to be more specific.
      setError(result.error);
      setPending(false);
      return;
    }
    router.refresh();
  }

  return (
    <Card>
      <CardContent>
        <p className="mb-4 text-sm text-muted-foreground">{INVITE_COPY}</p>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input id="email" name="email" type="email" required autoComplete="email" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              name="password"
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
            />
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}

          <Button type="submit" className="w-full" disabled={pending || !token}>
            {pending ? "Joining…" : "Accept invitation"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
