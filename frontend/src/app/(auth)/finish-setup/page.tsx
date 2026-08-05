"use client";

/**
 * Recovery screen for a half-completed signup: the Supabase account exists
 * and can sign in, but org bootstrap never succeeded, so there is no Rowan
 * organization behind it.
 *
 * Without this the account is bricked — every app page 401s, signing up again
 * reports "already registered", and signing in lands back on the same crash.
 * `(app)/layout.tsx` routes here when `/api/v1/me` returns 401.
 *
 * The tone is deliberately matter-of-fact rather than apologetic: per
 * CLAUDE.md this should read as a capable colleague picking up a dropped
 * thread, not an error state.
 */

import { useState } from "react";

import { bootstrapExistingUser } from "@/app/(auth)/actions";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function FinishSetupPage() {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setPending(true);
    setError(null);

    const result = await bootstrapExistingUser(new FormData(e.currentTarget));
    if (result?.error) {
      setError(result.error);
      setPending(false);
    }
  }

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="mb-5 space-y-1.5">
          <h2 className="text-sm font-medium">One more step</h2>
          <p className="text-sm text-muted-foreground">
            Your account is ready, but Rowan doesn&apos;t have your business on file yet.
            Add it and you&apos;re set.
          </p>
        </div>

        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="organizationName">Business name</Label>
            <Input id="organizationName" name="organizationName" required autoFocus />
          </div>
          <div className="space-y-2">
            <Label htmlFor="fullName">Your name</Label>
            <Input id="fullName" name="fullName" />
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}

          <Button type="submit" className="w-full" disabled={pending}>
            {pending ? "Setting up…" : "Finish setup"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
