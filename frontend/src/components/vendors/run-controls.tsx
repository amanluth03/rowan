"use client";

import { useTransition } from "react";
import { Pause, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { pauseRunAction, resumeRunAction } from "@/app/actions";
import { toast } from "sonner";
import type { RunStatus } from "@/lib/types";

export function RunControls({ runId, status }: { runId: string; status: RunStatus }) {
  const [isPending, startTransition] = useTransition();

  if (status === "paused") {
    return (
      <Button
        size="sm"
        variant="outline"
        disabled={isPending}
        onClick={() =>
          startTransition(async () => {
            const result = await resumeRunAction({ runId });
            toast(result.message);
          })
        }
      >
        <Play className="size-4" />
        Resume
      </Button>
    );
  }

  return (
    <Button
      size="sm"
      variant="outline"
      disabled={isPending || status !== "active"}
      onClick={() =>
        startTransition(async () => {
          const result = await pauseRunAction({ runId, reason: "PM takeover from vendor detail" });
          toast(result.message);
        })
      }
    >
      <Pause className="size-4" />
      Pause — I&apos;ll take over
    </Button>
  );
}
