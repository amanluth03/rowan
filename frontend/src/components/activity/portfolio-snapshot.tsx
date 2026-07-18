import Link from "next/link";
import type { PortfolioSnapshot } from "@/lib/api/read-models";
import { formatCents } from "@/lib/format";
import { cn } from "@/lib/utils";

function Tile({
  label,
  value,
  href,
  tone = "default",
}: {
  label: string;
  value: React.ReactNode;
  href?: string;
  tone?: "default" | "warn" | "error" | "good";
}) {
  const toneClass = {
    default: "text-foreground",
    good: "text-emerald-600 dark:text-emerald-400",
    warn: "text-amber-600 dark:text-amber-400",
    error: "text-rose-600 dark:text-rose-400",
  }[tone];

  const content = (
    <div className="flex flex-col gap-1 px-4 py-3">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <span className={cn("text-2xl font-semibold tabular-nums tracking-tight", toneClass)}>{value}</span>
    </div>
  );

  if (href) {
    return (
      <Link href={href} className="transition-colors hover:bg-muted/60">
        {content}
      </Link>
    );
  }
  return content;
}

export function PortfolioSnapshotStrip({ snapshot }: { snapshot: PortfolioSnapshot }) {
  return (
    <div className="grid grid-cols-2 divide-x divide-y divide-border border-b border-border sm:grid-cols-3 sm:divide-y-0 lg:grid-cols-6">
      <Tile label="Vendors tracked" value={snapshot.totalVendors} href="/vendors" />
      <Tile label="Compliant" value={snapshot.compliant} tone="good" href="/vendors?status=compliant" />
      <Tile label="Expiring soon" value={snapshot.expiringSoon} tone="warn" href="/vendors?status=expiring_soon" />
      <Tile label="Needs your review" value={snapshot.needsReview} tone={snapshot.needsReview > 0 ? "warn" : "default"} href="/review" />
      <Tile label="Escalated" value={snapshot.escalated} tone={snapshot.escalated > 0 ? "error" : "default"} href="/vendors?status=escalated" />
      <Tile label="LLM spend, this month" value={formatCents(snapshot.llmSpendCentsThisMonth)} />
    </div>
  );
}
