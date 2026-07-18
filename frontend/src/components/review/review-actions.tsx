"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Check, MessageSquareText, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { approveReviewAction, rejectReviewAction, requestRevisionAction } from "@/app/actions";

export function ReviewActions({ escalationId, vendorName }: { escalationId: string; vendorName: string }) {
  const [isPending, startTransition] = useTransition();
  const [rejectOpen, setRejectOpen] = useState(false);
  const [revisionOpen, setRevisionOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [revisionMessage, setRevisionMessage] = useState(
    `Hi — thanks for sending this over. We need an updated certificate before we can file it. Could you have your broker resend with the corrections noted, and reply here when it's ready?`,
  );
  const router = useRouter();

  function afterCommand(message: string) {
    toast(message);
    router.refresh();
  }

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="review-actions">
      <Button
        size="sm"
        disabled={isPending}
        data-testid="review-approve"
        onClick={() =>
          startTransition(async () => {
            const result = await approveReviewAction({ escalationId });
            afterCommand(result.message);
          })
        }
      >
        <Check className="size-4" />
        Approve
      </Button>

      <Dialog open={revisionOpen} onOpenChange={setRevisionOpen}>
        <DialogTrigger asChild>
          <Button size="sm" variant="outline" disabled={isPending} data-testid="review-request-revision">
            <MessageSquareText className="size-4" />
            Request revision
          </Button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Request a revised certificate</DialogTitle>
            <DialogDescription>
              Rowan will email {vendorName} with this note and wait for a new certificate. This counts against the outreach budget for the cycle.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="revision-message">Message to vendor</Label>
            <Textarea id="revision-message" rows={5} value={revisionMessage} onChange={(e) => setRevisionMessage(e.target.value)} />
          </div>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="ghost">Cancel</Button>
            </DialogClose>
            <Button
              disabled={isPending || revisionMessage.trim().length === 0}
              onClick={() =>
                startTransition(async () => {
                  const result = await requestRevisionAction({ escalationId, message: revisionMessage });
                  setRevisionOpen(false);
                  afterCommand(result.message);
                })
              }
            >
              Send request
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
        <DialogTrigger asChild>
          <Button size="sm" variant="outline" disabled={isPending} className="text-rose-600 hover:text-rose-700" data-testid="review-reject">
            <X className="size-4" />
            Reject
          </Button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject this certificate</DialogTitle>
            <DialogDescription>
              This parks {vendorName} in Escalated without asking Rowan to keep chasing. Use this when you&apos;ll handle it yourself.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="reject-reason">Reason (kept in the trace)</Label>
            <Textarea id="reject-reason" rows={3} value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} placeholder="e.g. Vendor is being replaced, no need to keep chasing." />
          </div>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="ghost">Cancel</Button>
            </DialogClose>
            <Button
              variant="destructive"
              disabled={isPending || rejectReason.trim().length === 0}
              onClick={() =>
                startTransition(async () => {
                  const result = await rejectReviewAction({ escalationId, reason: rejectReason });
                  setRejectOpen(false);
                  afterCommand(result.message);
                })
              }
            >
              Reject
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
