"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { bootstrapOrganization } from "@/app/(auth)/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { createBrowserClient } from "@/lib/supabase/browser";

export default function SignupPage() {
  const router = useRouter();
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

    // The session cookie now exists, so the server action can call the
    // Rowan API as this user.
    const result = await bootstrapOrganization(form);
    if (result?.error) {
      setError(result.error);
      setPending(false);
      return;
    }
    router.refresh();
  }

  return (
    <Card>
      <CardContent>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="organizationName">Business name</Label>
            <Input id="organizationName" name="organizationName" required />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="fullName">Your name</Label>
            <Input id="fullName" name="fullName" />
          </div>
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

          <Button type="submit" className="w-full" disabled={pending}>
            {pending ? "Creating your account…" : "Create account"}
          </Button>

          <p className="text-center text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link href="/login" className="underline underline-offset-4">Sign in</Link>
          </p>
        </form>
      </CardContent>
    </Card>
  );
}
