import { cn } from "@/lib/utils";
import type { ComplianceStatus, EventSeverity, RunState } from "@/lib/types";
import { complianceStatusStyles, runStateStyles, severityStyles } from "@/lib/status-styles";

function Dot({ className }: { className: string }) {
  return <span className={cn("inline-block size-1.5 rounded-full", className)} />;
}

export function ComplianceStatusBadge({ status, className }: { status: ComplianceStatus; className?: string }) {
  const s = complianceStatusStyles[status];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium", s.badgeClass, className)}>
      <Dot className={s.dotClass} />
      {s.label}
    </span>
  );
}

export function RunStateBadge({ state, className }: { state: RunState; className?: string }) {
  const s = runStateStyles[state];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium", s.badgeClass, className)}>
      <Dot className={s.dotClass} />
      {s.label}
    </span>
  );
}

export function SeverityBadge({ severity, className }: { severity: EventSeverity; className?: string }) {
  const s = severityStyles[severity];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium", s.badgeClass, className)}>
      <Dot className={s.dotClass} />
      {s.label}
    </span>
  );
}
