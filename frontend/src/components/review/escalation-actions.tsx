"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { CheckCircle2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { resolveEscalationAction } from "@/app/actions";

export function EscalationActions({ escalationId }: { escalationId: string }) {
  const [isPending, startTransition] = useTransition();
  const router = useRouter();

  function afterCommand(message: string) {
    toast(message);
    router.refresh();
  }

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="escalation-actions">
      <Button
        size="sm"
        variant="outline"
        disabled={isPending}
        data-testid="escalation-keep-chasing"
        onClick={() =>
          startTransition(async () => {
            const result = await resolveEscalationAction({ escalationId, resolution: "keep_chasing" });
            afterCommand(result.message);
          })
        }
      >
        <RefreshCw className="size-4" />
        Keep chasing
      </Button>
      <Button
        size="sm"
        disabled={isPending}
        data-testid="escalation-resolve"
        onClick={() =>
          startTransition(async () => {
            const result = await resolveEscalationAction({ escalationId, resolution: "resolved" });
            afterCommand(result.message);
          })
        }
      >
        <CheckCircle2 className="size-4" />
        Mark resolved
      </Button>
    </div>
  );
}
