"use client";

import { useState, useTransition } from "react";
import { toast } from "sonner";
import { UserPlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { inviteAssistant } from "@/app/(app)/settings/team/actions";

export function InviteForm() {
  const [email, setEmail] = useState("");
  const [isPending, startTransition] = useTransition();

  return (
    <form
      className="flex flex-col gap-3 sm:flex-row sm:items-end"
      data-testid="invite-form"
      onSubmit={(e) => {
        e.preventDefault();
        const trimmed = email.trim();
        if (!trimmed) return;
        startTransition(async () => {
          const result = await inviteAssistant((() => {
            const fd = new FormData();
            fd.set("email", trimmed);
            return fd;
          })());
          if (result.error) {
            toast(result.error);
            return;
          }
          toast(`Invited ${trimmed}. Rowan emailed them a link to join.`);
          setEmail("");
        });
      }}
    >
      <div className="flex-1 space-y-1.5">
        <Label htmlFor="invite-email">Invite an assistant</Label>
        <Input
          id="invite-email"
          type="email"
          required
          placeholder="assistant@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          data-testid="invite-email-input"
        />
      </div>
      <Button type="submit" disabled={isPending || email.trim().length === 0} data-testid="invite-submit">
        <UserPlus className="size-4" />
        Send invite
      </Button>
    </form>
  );
}
