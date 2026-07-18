import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Inbox,
  Mail,
} from "lucide-react";
import type { ActivityFeedItemKind } from "@/lib/types";
import { cn } from "@/lib/utils";

const config: Record<ActivityFeedItemKind, { icon: React.ComponentType<{ className?: string }>; className: string }> = {
  run_filed: { icon: CheckCircle2, className: "bg-emerald-50 text-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-400" },
  outreach_sent: { icon: Mail, className: "bg-sky-50 text-sky-600 dark:bg-sky-950/50 dark:text-sky-400" },
  follow_up_sent: { icon: Mail, className: "bg-sky-50 text-sky-600 dark:bg-sky-950/50 dark:text-sky-400" },
  document_received: { icon: Inbox, className: "bg-sky-50 text-sky-600 dark:bg-sky-950/50 dark:text-sky-400" },
  validation_failed: { icon: AlertTriangle, className: "bg-amber-50 text-amber-600 dark:bg-amber-950/50 dark:text-amber-400" },
  needs_human_review: { icon: AlertTriangle, className: "bg-amber-50 text-amber-600 dark:bg-amber-950/50 dark:text-amber-400" },
  escalated_to_pm: { icon: AlertOctagon, className: "bg-rose-50 text-rose-600 dark:bg-rose-950/50 dark:text-rose-400" },
  human_resolved: { icon: CheckCircle2, className: "bg-emerald-50 text-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-400" },
  renewal_due_soon: { icon: Clock, className: "bg-slate-100 text-slate-600 dark:bg-slate-800/60 dark:text-slate-300" },
};

export function ActivityIcon({ kind, className }: { kind: ActivityFeedItemKind; className?: string }) {
  const { icon: Icon, className: iconClassName } = config[kind];
  return (
    <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-full", iconClassName, className)}>
      <Icon className="size-4" />
    </span>
  );
}
