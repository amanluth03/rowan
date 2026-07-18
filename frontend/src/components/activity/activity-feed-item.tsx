import Link from "next/link";
import { ArrowRight } from "lucide-react";
import type { ActivityFeedItemDTO } from "@/lib/types";
import { ActivityIcon } from "./activity-icon";
import { formatDate, formatVendorRole, relativeTime } from "@/lib/format";
import { RunStateBadge } from "@/components/shared/status-badge";
import { DocumentEvidenceChip, CitationEvidenceChip } from "@/components/shared/evidence";
import { cn } from "@/lib/utils";

export function ActivityFeedItem({ item }: { item: ActivityFeedItemDTO }) {
  return (
    <li
      className={cn(
        "relative flex gap-3 border-b border-border/70 px-6 py-4 last:border-b-0",
        item.actionRequired && "bg-amber-50/30 dark:bg-amber-950/10",
      )}
    >
      <ActivityIcon kind={item.kind} />

      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
          <div className="min-w-0">
            <p className="text-sm leading-snug text-foreground">
              <Link href={`/vendors/${item.vendorId}`} className="font-medium hover:underline underline-offset-2">
                {item.vendorName}
              </Link>{" "}
              <span className="text-muted-foreground">· {formatVendorRole(item.vendorRole)}</span>
            </p>
            <p className="mt-0.5 text-[15px] leading-snug text-foreground">{item.headline}</p>
            {item.detail ? <p className="mt-1 text-sm leading-snug text-muted-foreground">{item.detail}</p> : null}
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1.5">
            <span className="text-xs text-muted-foreground" title={item.occurredAt}>{relativeTime(item.occurredAt)}</span>
            <RunStateBadge state={item.state} />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 pt-0.5">
          {item.evidence.document ? <DocumentEvidenceChip document={item.evidence.document} /> : null}
          {item.evidence.sourceCitation !== undefined && (item.kind === "run_filed" || item.kind === "needs_human_review") ? (
            <CitationEvidenceChip citation={item.evidence.sourceCitation} />
          ) : null}
          {item.evidence.validTo ? (
            <span className="rounded-md border border-border bg-muted/40 px-2 py-1 text-xs text-muted-foreground">
              Valid through {formatDate(item.evidence.validTo)}
            </span>
          ) : null}
          <Link
            href={`/runs/${item.runId}`}
            className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline underline-offset-2"
          >
            View trace <ArrowRight className="size-3" />
          </Link>
        </div>
      </div>
    </li>
  );
}
