import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { SeverityBadge } from "@/components/shared/status-badge";
import { DocumentEvidenceChip } from "@/components/shared/evidence";
import { CoverageComparisonList } from "@/components/shared/coverage-comparison";
import { ReviewActions } from "./review-actions";
import { EscalationActions } from "./escalation-actions";
import type { ReviewQueueItemDTO } from "@/lib/types";
import { formatVendorRole, relativeTime } from "@/lib/format";

const reasonLabels: Record<string, string> = {
  validation_failed: "Validation failed",
  low_confidence_extraction: "Low-confidence extraction",
  no_response: "No vendor response",
  no_requirements_on_file: "No requirements on file",
  rejected_by_pm: "Rejected by you",
};

export function ReviewItemCard({ item }: { item: ReviewQueueItemDTO }) {
  const isNeedsReview = item.kind === "needs_human_review";

  return (
    <Card className="overflow-hidden gap-0 py-0" data-testid="review-item" data-escalation-id={item.escalationId}>
      <CardHeader className="border-b border-border py-4 [.border-b]:pb-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <Link href={`/vendors/${item.vendorId}`} className="text-sm font-semibold hover:underline underline-offset-2">
                {item.vendorName}
              </Link>
              <span className="text-xs text-muted-foreground">{formatVendorRole(item.vendorRole)}</span>
              <SeverityBadge severity={item.severity} />
              <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
                {reasonLabels[item.reasonCode] ?? item.reasonCode.replaceAll("_", " ")}
              </span>
            </div>
            <p className="text-sm leading-snug text-foreground">{item.summary}</p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1.5">
            <span className="text-xs text-muted-foreground">{relativeTime(item.createdAt)}</span>
            <Link href={`/runs/${item.runId}`} className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline underline-offset-2">
              View trace <ArrowRight className="size-3" />
            </Link>
          </div>
        </div>
        {item.document ? (
          <div className="mt-1">
            <DocumentEvidenceChip document={item.document} />
          </div>
        ) : null}
        {!item.faithfulnessOk ? (
          <p className="mt-2 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400">
            Faithfulness check failed — at least one asserted line didn&apos;t trace back to a retrieved requirement. Held for review regardless of pass/fail.
          </p>
        ) : null}
      </CardHeader>

      {isNeedsReview && item.comparison.length > 0 ? <CoverageComparisonList comparison={item.comparison} /> : null}

      <CardContent className="flex items-center justify-between gap-3 border-t border-border bg-muted/20 py-3">
        <p className="text-xs text-muted-foreground">
          {isNeedsReview ? "Approving overrides the failed validation with your sign-off." : "Decide how Rowan should proceed."}
        </p>
        {isNeedsReview ? (
          <ReviewActions escalationId={item.escalationId} vendorName={item.vendorName} />
        ) : (
          <EscalationActions escalationId={item.escalationId} />
        )}
      </CardContent>
    </Card>
  );
}
