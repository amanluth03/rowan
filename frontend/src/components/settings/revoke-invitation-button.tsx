"use client";

import { useTransition } from "react";
import { toast } from "sonner";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { revokeInvitation } from "@/app/(app)/settings/team/actions";

export function RevokeInvitationButton({ invitationId, email }: { invitationId: string; email: string }) {
  const [isPending, startTransition] = useTransition();

  return (
    <Button
      variant="ghost"
      size="sm"
      disabled={isPending}
      aria-label={`Revoke invitation for ${email}`}
      data-testid="revoke-invitation"
      onClick={() =>
        startTransition(async () => {
          const result = await revokeInvitation(invitationId);
          if (result.error) {
            toast(result.error);
            return;
          }
          toast(`Revoked the invitation for ${email}.`);
        })
      }
    >
      <X className="size-3.5" />
      Revoke
    </Button>
  );
}
