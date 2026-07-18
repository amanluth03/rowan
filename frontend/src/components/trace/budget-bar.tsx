import { Progress } from "@/components/ui/progress";
import { formatCents } from "@/lib/format";
import type { RunTraceDTO } from "@/lib/types";

function Meter({ label, used, cap, formatValue }: { label: string; used: number; cap: number; formatValue: (n: number) => string }) {
  const pct = cap > 0 ? Math.min(100, (used / cap) * 100) : 0;
  return (
    <div className="min-w-40 flex-1">
      <div className="mb-1.5 flex items-baseline justify-between text-xs">
        <span className="font-medium text-muted-foreground">{label}</span>
        <span className="tabular-nums text-foreground">{formatValue(used)} / {formatValue(cap)}</span>
      </div>
      <Progress value={pct} className="h-1.5" />
    </div>
  );
}

export function BudgetBar({ budget }: { budget: RunTraceDTO["budget"] }) {
  return (
    <div className="flex flex-wrap gap-6 rounded-lg border border-border bg-muted/20 px-4 py-3.5">
      <Meter label="Outreach emails" used={budget.outreachEmailCount} cap={budget.maxOutreach} formatValue={(n) => String(n)} />
      <Meter label="Model calls, this doc" used={budget.llmCallCount} cap={budget.maxLlmCallsPerDoc} formatValue={(n) => String(n)} />
      <Meter label="Spend, this run" used={budget.costCentsSpent} cap={budget.budgetCostCapCents} formatValue={formatCents} />
    </div>
  );
}
